import logging
import json
import subprocess
from typing import Any, Dict, Optional
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import requests

# Create logger
logger = logging.getLogger(__name__)
DEFAULT_REQUEST_TIMEOUT = 60

def get_credentials(CERTIFICATE_PATH: str, PRIVATE_KEY_PATH: str, TRUST_ANCHOR_ARN: str, PROFILE_ARN: str, ROLE_ARN: str, REGION: str):
    """
    Runs the aws_signing_helper tool to retrieve temporary credentials
    
    Args:
        CERTIFICATE_PATH: full pathname to DSS's TLS certificate
        PRIVATE_KEY_PATH: full pathname to DSS's TLS private key
        TRUST_ANCHOR_ARN: ARN of trust anchor configured on IAM Roles Anywhere
        PROFILE_ARN: ARN of profile configured on IAM Roles Anywhere
        ROLE_ARN: ARN of target role configured on IAM Roles Anywhere
        REGION: region where IAM Roles Anywhere is setup
    
    Returns:
        dict: JSON payload of the response.
    """
    missing_args = [
        name for name, value in {
            "CERTIFICATE_PATH": CERTIFICATE_PATH,
            "PRIVATE_KEY_PATH": PRIVATE_KEY_PATH,
            "TRUST_ANCHOR_ARN": TRUST_ANCHOR_ARN,
            "PROFILE_ARN": PROFILE_ARN,
            "ROLE_ARN": ROLE_ARN,
            "REGION": REGION,
        }.items() if not value
    ]
    if missing_args:
        raise ValueError("Missing IAM Roles Anywhere configuration: {}".format(", ".join(missing_args)))

    cmd = [
        "aws_signing_helper", "credential-process",
        "--certificate", CERTIFICATE_PATH,
        "--private-key", PRIVATE_KEY_PATH,
        "--trust-anchor-arn", TRUST_ANCHOR_ARN,
        "--profile-arn", PROFILE_ARN,
        "--role-arn", ROLE_ARN,
        "--region", REGION
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        creds = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise RuntimeError("aws_signing_helper is not installed or not available on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"Failed to get IAM Roles Anywhere credentials: {stderr}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("aws_signing_helper returned invalid JSON credentials") from exc

    return creds


def get_assumed_role_session(base_session, target_role_arn, region, session_name="cross-account-session"):
    """Assume cross-account target role and return a new boto3 session"""
    sts = base_session.client('sts')
    response = sts.assume_role(
        RoleArn=target_role_arn,
        RoleSessionName=session_name
    )
    creds = response['Credentials']
    
    return boto3.Session(
        aws_access_key_id=creds['AccessKeyId'],
        aws_secret_access_key=creds['SecretAccessKey'],
        aws_session_token=creds['SessionToken'],
        region_name=region
    )


def _redact_headers(headers: dict) -> dict:
    redacted = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "x-api-key", "x-amz-security-token"}:
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


def call_api_gateway(session, url, method, region, api_key, payload, ca_path, timeout: int = DEFAULT_REQUEST_TIMEOUT):
    """
    Call API Gateway with SigV4 authentication using boto3
    
    Args:
        session: boto3 session
        method: HTTP request method
        region: aws region
        api_key: API key in use at API Gateway for authentication
        payload: Data of the request
        ca_path: Full pathname of GE's cabundle.p
        file in DSS
    
    Returns:
        dict: payload of the response.
    """
    if not session:
        raise ValueError("AWS session is required")
    if not url:
        raise ValueError("API Gateway URL is required")
    if not api_key:
        raise ValueError("API key is required")
    if not region:
        raise ValueError("AWS region is required")
    if not ca_path:
        raise ValueError("Custom CA path is required")

    request = AWSRequest(
        method=method,
        url=url,
        data=json.dumps(payload) if payload else None,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    SigV4Auth(session.get_credentials(), 'execute-api', region).add_auth(request)
    
    # Prepare headers for requests (remove Host to let requests handle connection)
    myheaders = dict(request.headers)
    myheaders.pop('Host', None)
    # Add the API Key into the request header.
    myheaders['x-api-key'] = api_key
 
    response = requests.request(
        method = method,
        url = url,
        headers = myheaders,
        data = request.body,
        verify = ca_path,
        timeout = timeout
    )
    
    logger.info("Sending request to API Gateway (%s %s)", method, url)
    logger.debug("=== Sending Request Headers: %s", _redact_headers(myheaders))
    logger.debug(f"=== Sending Request Body: {request.body}")    
    return response

def test_caller_identity(session):
    """
    Function to verify identity via AWS CLI with IAM Roles Anywhere credentials
    
    Args:
        session: boto3 session
    
    Returns:
        dict: output from sts.get_caller_identity
    """
    sts = session.client('sts')
    identity = sts.get_caller_identity()
    logger.info("Caller Identity:")
    logger.info(json.dumps(identity, indent=2, default=str))
    return identity

def create_auth_headers(api_key: str) -> dict:
    """
    Create authentication headers for the API request.

    Args:
        api_key: The API key for authorization.

    Returns:
        dict: Headers with authorization and content type.
    """
    logger.debug("Creating authentication headers")
    
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": api_key
    }

def create_custom_ge_payload_multimode_chat(model: str, query: dict, settings: dict) -> dict:
    """
    Create the JSON payload for the API request.

    Args:
        model: The model to use for the request.
        query: The query object containing messages.
        settings: Request settings/parameters.

    Returns:
        dict: JSON payload for the API request.
    """
    logger.debug(f"Creating payload for model: {model}")
    # Transform messages to the format expected by OpenAI-compatible APIs for tool calling.
    original_messages = query.get('messages', [])
    transformed_messages = []
    for message in original_messages:
        if message.get('role') == 'assistant' and 'toolCalls' in message:
            # Convert Dataiku 'toolCalls' to OpenAI 'tool_calls' and add 'content: null'.
            transformed_messages.append({
                'role': 'assistant',
                'content': None,
                'tool_calls': message['toolCalls']
            })
        elif message.get('role') == 'tool' and 'toolOutputs' in message:
            # Convert Dataiku 'toolOutputs' array into individual tool messages.
            for tool_output in message.get('toolOutputs', []):
                transformed_messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_output.get('callId'),
                    'content': str(tool_output.get('output', '')) # Content must be a string.
                })
        elif 'parts' in message:
            # Handle multimodal messages (text + images)
            logger.debug(f"Processing multimodal message with {len(message['parts'])} parts")
            content_parts = []
            for part in message['parts']:
                part_type = part.get('type')
                if part_type == 'TEXT':
                    # Add text content
                    content_parts.append({
                        'type': 'text',
                        'text': part.get('text', '')
                    })
                elif part_type == 'IMAGE_INLINE':
                    # Add inline image content (base64 encoded)
                    inline_image = part.get('inlineImage', '')
                    # Determine image format from base64 data if possible
                    # Most images will be PNG or JPEG
                    mime_type = get_mimetype(inline_image)
                    
                    content_parts.append({
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:{mime_type};base64,{inline_image}'
                        }
                    })
                    logger.debug("Added inline image to message")
                elif part_type == 'IMAGE_URL':
                    # Add image URL
                    content_parts.append({
                        'type': 'image_url',
                        'image_url': {
                            'url': part.get('url', '')
                        }
                    })
                    logger.debug(f"Added image URL to message: {part.get('url', '')}")

            # Create transformed message with content parts
            transformed_messages.append({
                'role': message.get('role'),
                'content': content_parts
            })
        else:
            # Keep other messages (e.g., user messages) as they are.
            transformed_messages.append(message)
            
    logger.debug(f"Transformed {len(original_messages)} messages to {len(transformed_messages)} messages")
    
    payload = {
        #"model": model,
        #"messages": transformed_messages
        #"applicationConfigId": "fd2b1f89-c740-48ae-9462-f6a7d79933a4",
        'inputs': transformed_messages
    }

    # Add optional settings if provided
    if settings:
        # Add common LLM parameters from settings
        if 'temperature' in settings:
            payload['temperature'] = settings['temperature']
        if 'maxOutputTokens' in settings:
            payload['max_tokens'] = settings['maxOutputTokens']
        if 'topP' in settings:
            payload['top_p'] = settings['topP']
        if 'presencePenalty' in settings:
            payload['presence_penalty'] = settings['presencePenalty']
        if 'frequencyPenalty' in settings:
            payload['frequency_penalty'] = settings['frequencyPenalty']
        if 'tools' in settings:
            payload['tools'] = settings['tools']
            payload['tool_choice'] = settings.get('tool_choice', 'auto')
            logger.debug(f"Added {len(settings['tools'])} tools to payload")
        if 'stream' in settings:
            payload['stream'] = settings.get('stream', False)

    logger.debug(f"Created payload with {len(payload)} keys")
    return payload

def calculate_cost(prompt_tokens: int, completion_tokens: int, prompt_cost: float, completion_cost: float) -> float:
    """
    Calculate the estimated cost of a request.

    Args:
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        prompt_cost: Cost per 1000 prompt tokens.
        completion_cost: Cost per 1000 completion tokens.

    Returns:
        float: Estimated cost in USD.
    """
    # Cost is per 1k tokens
    prompt_cost_total = (prompt_tokens / 1000) * prompt_cost
    completion_cost_total = (completion_tokens / 1000) * completion_cost
    total_cost = prompt_cost_total + completion_cost_total
    logger.debug(f"Calculated cost: ${total_cost:.6f} (prompt: {prompt_tokens} tokens, completion: {completion_tokens} tokens)")
    return total_cost

def parse_response(response_data: dict, prompt_cost: float = 0.0, completion_cost: float = 0.0) -> dict:
    """
    Parse the API response and extract relevant information.

    Args:
        response_data: Raw JSON response from the API.
        prompt_cost: Cost per 1000 prompt tokens.
        completion_cost: Cost per 1000 completion tokens.

    Returns:
        dict: Parsed result with text, tokens, cost, and tool calls.
    """
    logger.debug("Parsing API response")
    result = {
        "text": "",  # Default fallback
        "promptTokens": 0,
        "completionTokens": 0,
        "estimatedCost": 0.0,
        "toolCalls": [],
    }
   
    #logger.debug(f"=== Received Response Body: {response_data}")

    # Parsing based on GE's response format:
    if 'body' in response_data:
        response_body = response_data['body']
        if isinstance(response_body, str):
            try:
                response_body = json.loads(response_body)
            except json.JSONDecodeError:
                logger.warning("Response body was not valid JSON")
                response_body = None

        if isinstance(response_body, dict):
            model_output = response_body.get('model_output', {})
            generated_text = model_output.get('generated_text')
            if generated_text is not None:
                result["text"] = generated_text
                logger.debug(f"Extracted text content of length: {len(result['text'])}")
            elif response_body.get("errorMessage"):
                raise ValueError(f"Gateway returned an error payload: {response_body['errorMessage']}")
    
    if 'choices' in response_data and len(response_data['choices']) > 0:
        choice = response_data['choices'][0]
        message = choice.get('message', {})

        # Extract text content
        content = message.get('content')
        if content:
            result["text"] = content
            logger.debug(f"Extracted text content of length: {len(content)}")

        # Extract tool calls if present
        tool_calls = message.get('tool_calls', [])
        if tool_calls:
            # For non-streaming, return the tool_calls object directly as per API response
            result["toolCalls"] = tool_calls
            logger.debug(f"Extracted {len(tool_calls)} tool calls")

        # Correct the finish reason. If tool calls are present, it must be 'tool_calls'.
        if result["toolCalls"]:
            result["finishReason"] = "tool_calls"
        else:
            result["finishReason"] = choice.get('finish_reason', 'stop')
        logger.debug(f"Finish reason: {result['finishReason']}")

    usage = response_data.get('usage', {})
    if not usage and isinstance(response_data.get("body"), dict):
        usage = response_data["body"].get("usage", {})
    if usage:
        result["promptTokens"] = usage.get('prompt_tokens', 0)
        result["completionTokens"] = usage.get('completion_tokens', 0) or (usage.get('total_tokens', 0) - result["promptTokens"])
        result["estimatedCost"] = calculate_cost(result["promptTokens"], result["completionTokens"], prompt_cost, completion_cost)

    if not result["text"] and not result["toolCalls"]:
        raise ValueError("Unable to parse a valid model response from the API payload")

    logger.info("Successfully parsed API response")
    return result

def get_mimetype(b64_string):
    """
    Helper to detect MIME type from Base64 string
    """
    # These are the Base64 "Magic Number" signatures for common formats
    signatures = {
        "iVBORw0KGgo": "image/png",
        "/9j/": "image/jpeg",
        "R0lGODlh": "image/gif",
        "UklGR": "image/webp"
    }
    for sig, mime in signatures.items():
        if b64_string.startswith(sig):
            return mime
    return "image/png"  # Fallback to PNG if unknown

def create_custom_ge_payload_embedding_text(model_id: str, image_path: Optional[str] = None) -> Dict[str, Any]:
    """Build and return an embedding request payload based on GE's requirements at Bedrock.

    :param model_id: The ID of the model to use.
    :param image_path: Path to the image file (required for case 4).
    :return: Payload dictionary configured for the specific test case.
    """

    # Define constant mapping for Case UUIDs
    CONFIG_IDS = {
        "embed-v4-global": "ba268aab-1e71-450a-a572-99b9c5dd8b08",
        "embed-english-v3": "e5ae9094-5576-4df3-abcd-db63c3ab7a13",
        "embed-multilingual-v3": "5a2ac66c-93ce-4ab3-a7b0-822a0945dac4"
    }

    if model_id.lower() == "embed-v4-global":
        return {
            "applicationConfigId": CONFIG_IDS['embed-v4-global'],
            "inputType": "search_document"
        }

    elif model_id.lower() == "embed-english-v3":
        return {
            "applicationConfigId": CONFIG_IDS['embed-english-v3'],
            "inputType": "search_document"
        }

    elif model_id.lower() == "embed-multilingual-v3":
        return {
            "applicationConfigId": CONFIG_IDS['embed-multilingual-v3'],
            "inputType": "search_query"
        }

    # elif model_id == "xxx":
    #     if not image_path or not os.path.isfile(image_path):
    #         raise FileNotFoundError(
    #             f"Valid image_path required for case 4. Got: {image_path}"
    #         )

    #     with open(image_path, "rb") as image_file:
    #         image_base64 = base64.b64encode(image_file.read()).decode("utf-8")

    #     return {
    #         "applicationConfigId": CONFIG_IDS['embed-english-v3'],
    #         "texts": ["Insurance claim document image."],
    #         "images": [image_base64],
    #         "inputType": "search_document",
    #     }

    else:
        raise ValueError(
            f"Invalid model_id '{model_id}'. Model ID not found."
        )
    
# def create_payload(model: str, query: dict, settings: dict) -> dict:
#     """
#     Create the JSON payload for the API request.

#     Args:
#         model: The model to use for the request.
#         query: The query object containing messages.
#         settings: Request settings/parameters.

#     Returns:
#         dict: JSON payload for the API request.
#     """
#     logger.debug(f"Creating payload for model: {model}")
#     # Transform messages to the format expected by OpenAI-compatible APIs for tool calling.
#     original_messages = query.get('messages', [])
#     transformed_messages = []
#     for message in original_messages:
#         if message.get('role') == 'assistant' and 'toolCalls' in message:
#             # Convert Dataiku 'toolCalls' to OpenAI 'tool_calls' and add 'content: null'.
#             transformed_messages.append({
#                 'role': 'assistant',
#                 'content': None,
#                 'tool_calls': message['toolCalls']
#             })
#         elif message.get('role') == 'tool' and 'toolOutputs' in message:
#             # Convert Dataiku 'toolOutputs' array into individual tool messages.
#             for tool_output in message.get('toolOutputs', []):
#                 transformed_messages.append({
#                     'role': 'tool',
#                     'tool_call_id': tool_output.get('callId'),
#                     'content': str(tool_output.get('output', '')) # Content must be a string.
#                 })
#         elif 'parts' in message:
#             # Handle multimodal messages (text + images)
#             logger.debug(f"Processing multimodal message with {len(message['parts'])} parts")
#             content_parts = []
#             for part in message['parts']:
#                 part_type = part.get('type')
#                 if part_type == 'TEXT':
#                     # Add text content
#                     content_parts.append({
#                         'type': 'text',
#                         'text': part.get('text', '')
#                     })
#                 elif part_type == 'IMAGE_INLINE':
#                     # Add inline image content (base64 encoded)
#                     inline_image = part.get('inlineImage', '')
#                     # Determine image format from base64 data if possible
#                     # Most images will be PNG or JPEG
#                     content_parts.append({
#                         'type': 'image_url',
#                         'image_url': {
#                             'url': f'data:image/png;base64,{inline_image}'
#                         }
#                     })
#                     logger.debug("Added inline image to message")
#                 elif part_type == 'IMAGE_URL':
#                     # Add image URL
#                     content_parts.append({
#                         'type': 'image_url',
#                         'image_url': {
#                             'url': part.get('url', '')
#                         }
#                     })
#                     logger.debug(f"Added image URL to message: {part.get('url', '')}")

#             # Create transformed message with content parts
#             transformed_messages.append({
#                 'role': message.get('role'),
#                 'content': content_parts
#             })
#         else:
#             # Keep other messages (e.g., user messages) as they are.
#             transformed_messages.append(message)

#     logger.debug(f"Transformed {len(original_messages)} messages to {len(transformed_messages)} messages")

#     payload = {
#         "model": model,
#         "messages": transformed_messages
#     }

#     # Add optional settings if provided
#     if settings:
#         # Add common LLM parameters from settings
#         if 'temperature' in settings:
#             payload['temperature'] = settings['temperature']
#         if 'maxOutputTokens' in settings:
#             payload['max_tokens'] = settings['maxOutputTokens']
#         if 'topP' in settings:
#             payload['top_p'] = settings['topP']
#         if 'presencePenalty' in settings:
#             payload['presence_penalty'] = settings['presencePenalty']
#         if 'frequencyPenalty' in settings:
#             payload['frequency_penalty'] = settings['frequencyPenalty']
#         if 'tools' in settings:
#             payload['tools'] = settings['tools']
#             payload['tool_choice'] = settings.get('tool_choice', 'auto')
#             logger.debug(f"Added {len(settings['tools'])} tools to payload")
#         if 'stream' in settings:
#             payload['stream'] = settings.get('stream', False)

#     logger.debug(f"Created payload with {len(payload)} keys")
#     return payload

# def parse_stream_chunk(chunk: str) -> dict:
#     """
#     Parses a single chunk from a streaming API response (SSE format).

#     Args:
#         chunk: A string chunk from the response stream, e.g., "data: {...}".

#     Returns:
#         A dictionary with the parsed data, which could be a text chunk,
#         a tool call chunk, a usage block, or a done signal.
#         Returns an empty dictionary for irrelevant lines.
#     """
#     if not chunk.startswith('data:'):
#         return {}

#     # Remove 'data: ' prefix and strip whitespace
#     json_str = chunk[len('data:'):].strip()

#     if not json_str:
#         return {}

#     if json_str == '[DONE]':
#         logger.debug("Received [DONE] signal in stream")
#         return {"done": True}

#     try:
#         data = json.loads(json_str)
#         parsed_chunk = {}

#         # Final usage block
#         if 'usage' in data:
#             parsed_chunk["usage"] = data['usage']
#             logger.debug(f"Received usage data: {data['usage']}")

#         # Assuming OpenAI-like streaming format
#         choices = data.get('choices', [])
#         if choices:
#             choice = choices[0]
#             delta = choice.get('delta', {})

#             # Text content chunk
#             content = delta.get('content')
#             if content is not None:
#                 parsed_chunk["text"] = content

#             # Tool call chunk
#             tool_calls = delta.get('tool_calls')
#             if tool_calls:
#                 parsed_chunk["tool_calls_chunk"] = tool_calls
#                 logger.debug(f"Received tool calls chunk: {len(tool_calls)} calls")

#             # Finish reason
#             finish_reason = choice.get('finish_reason') # Can be None
#             if finish_reason is not None:
#                 parsed_chunk["finish_reason"] = finish_reason
#                 logger.debug(f"Received finish reason: {finish_reason}")
#         return parsed_chunk

#     except (json.JSONDecodeError, IndexError) as e:
#         # Ignore chunks that are not valid JSON or don't have the expected structure
#         logger.warning(f"Failed to parse stream chunk: {e}")
#         return {}

# def process_stream(response, prompt_cost: float, completion_cost: float) -> "Iterator[dict]":
#     """Helper generator to process and yield streaming responses, assembling tool calls and usage."""
#     logger.info("Starting to process streaming response")
#     final_usage = None
#     final_finish_reason = None
#     has_tool_calls = False
#     chunk_count = 0

#     for line in response.iter_lines():
#         if not line:
#             continue

#         decoded_line = line.decode('utf-8')
#         chunk = parse_stream_chunk(decoded_line)

#         if chunk.get("done"):
#             logger.debug("Stream processing complete")
#             break

#         if "text" in chunk and chunk["text"] is not None:
#             chunk_count += 1
#             yield {"text": chunk["text"]}

#         if "tool_calls_chunk" in chunk:
#             # The model sends the complete tool call object in a single chunk.
#             # We can yield it directly without needing to assemble it across multiple chunks.
#             yield {"toolCalls": chunk["tool_calls_chunk"]}
#             has_tool_calls = True

#         if "usage" in chunk:
#             final_usage = chunk["usage"]

#         if "finish_reason" in chunk:
#             final_finish_reason = chunk["finish_reason"]

#     logger.debug(f"Processed {chunk_count} text chunks from stream")

#     # After the loop, yield the final usage stats
#     final_stats = {}
#     if final_usage:
#         prompt_tokens = final_usage.get("prompt_tokens", 0)
#         completion_tokens = final_usage.get("completion_tokens", 0) or final_usage.get("total_tokens", 0) - prompt_tokens
#         cost = calculate_cost(prompt_tokens, completion_tokens, prompt_cost, completion_cost)
#         final_stats.update({"promptTokens": prompt_tokens, "completionTokens": completion_tokens, "estimatedCost": cost})

#     # Add the corrected finish reason to the final stats chunk
#     if has_tool_calls:
#         final_stats["finishReason"] = "tool_calls"
#     elif final_finish_reason:
#         final_stats["finishReason"] = final_finish_reason

#     if final_stats:
#         logger.info(f"Stream completed with finish reason: {final_stats.get('finishReason')}")
#         # The final chunk containing metadata should be wrapped under a 'footer' key
#         # for the Dataiku LLM framework to recognize it as the footer.
#         yield {"footer": final_stats}
