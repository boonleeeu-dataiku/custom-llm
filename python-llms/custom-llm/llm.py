# This file is the implementation of custom LLM ge-custom-sm-llm
from dataiku.llm.python import BaseLLM
from dataiku.llm.python import BaseEmbeddingModel

import logging
import requests
from customllm import utils

import boto3

# Create logger
logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    pass


class AWSGatewayMixin:
    def _load_common_config(self, config: dict, plugin_config: dict) -> None:
        self.config = config
        self.plugin_config = plugin_config

        api_cfg = config.get("api_keys") or {}
        iam_cfg = config.get("iam_roles_anywhere") or {}
        ca_cfg = config.get("custom_ca_path") or {}

        self.api_gateway_url = api_cfg.get("api_gateway_url")
        self.api_key = api_cfg.get("api_key")
        self.model = config.get("model")
        self.prompt_cost = config.get("prompt_cost", 0.0)
        self.completion_cost = config.get("completion_cost", 0.0)

        self.certificate_path = iam_cfg.get("certificate_path")
        self.private_key_path = iam_cfg.get("private_key_path")
        self.trust_anchor_arn = iam_cfg.get("trust_anchor_arn")
        self.profile_arn = iam_cfg.get("profile_arn")
        self.base_role_arn = iam_cfg.get("base_role_arn")
        self.target_role_enable = bool(iam_cfg.get("target_role_enable", False))
        self.target_role_arn = iam_cfg.get("target_role_arn")
        self.region = iam_cfg.get("region") or "ap-southeast-1"
        self.ca_path = ca_cfg.get("ca_path") or "/data_dataiku_design/ge-cabundle.pem"

    def _validate_common_config(self) -> None:
        missing = []
        if not self.api_gateway_url:
            missing.append("api_keys.api_gateway_url")
        if not self.api_key:
            missing.append("api_keys.api_key")
        if not self.model:
            missing.append("model")
        if not self.certificate_path:
            missing.append("iam_roles_anywhere.certificate_path")
        if not self.private_key_path:
            missing.append("iam_roles_anywhere.private_key_path")
        if not self.trust_anchor_arn:
            missing.append("iam_roles_anywhere.trust_anchor_arn")
        if not self.profile_arn:
            missing.append("iam_roles_anywhere.profile_arn")
        if not self.base_role_arn:
            missing.append("iam_roles_anywhere.base_role_arn")
        if not self.region:
            missing.append("iam_roles_anywhere.region")
        if not self.ca_path:
            missing.append("custom_ca_path.ca_path")
        if self.target_role_enable and not self.target_role_arn:
            missing.append("iam_roles_anywhere.target_role_arn")

        if missing:
            raise ConfigError("Missing required plugin configuration: {}".format(", ".join(missing)))

    def _create_aws_session(self):
        logger.info("Getting credentials from IAM Roles Anywhere...")
        creds = utils.get_credentials(
            self.certificate_path,
            self.private_key_path,
            self.trust_anchor_arn,
            self.profile_arn,
            self.base_role_arn,
            self.region,
        )

        logger.info("Creating boto3 session with temporary credentials...")
        base_session = boto3.Session(
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken'],
            region_name=self.region
        )

        if self.target_role_enable:
            return utils.get_assumed_role_session(base_session, self.target_role_arn, self.region)
        return base_session
    
class MyLLM(AWSGatewayMixin, BaseLLM):
    def __init__(self):
        """
        Constructor for the MyLLM class.
        Initializes configuration and client-related attributes.
        """
        self.config = None
        self.plugin_config = None
        self.api_gateway_url = None
        self.api_key = None
        self.model = None
        self.prompt_cost = 0.0
        self.completion_cost = 0.0
        
        self.certificate_path = None
        self.private_key_path = None
        self.trust_anchor_arn = None
        self.profile_arn = None
        self.base_role_arn = None
        self.target_role_enable = False
        self.target_role_arn = None
        self.region = None


    def set_config(self, config: dict, plugin_config: dict) -> None:
        """
        Sets the configuration for the LLM. This is used to read the paramteres set in the LLM Mesh Connection

        Args:
            config (dict): A dictionary of the parameters set by the user in the LLM service settings.
            plugin_config (dict): A dictionary of the plugin-level settings.
        """
        logger.info("Setting configuration for MyLLM")
        self._load_common_config(config, plugin_config)
        self._validate_common_config()
        

    def process(self, query, settings, trace):
        """
        Processes a query for a non-streaming response.

        Args:
            query (dict): The input query, typically containing a 'messages' list.
            settings (dict): A dictionary of settings for the API call (e.g., temperature).
            trace: A tracing object for logging.

        Returns:
            dict: The complete parsed response from the LLM.

        Raises:
            ConnectionError: If the API request fails.
        """       
        
        session = self._create_aws_session()

        logger.info("Processing non-streaming request")
        # This method handles non-streaming requests.
        # We explicitly set stream to False in the payload.
        request_settings = dict(settings or {})
        request_settings['stream'] = False
        payload = utils.create_custom_ge_payload_multimode_chat(self.model, query, request_settings)
                
        try:
            response = utils.call_api_gateway(session, self.api_gateway_url, "POST", self.region, self.api_key, payload, self.ca_path)
            logger.info("Received response from API")
            logger.info(f"Response status code: {response.status_code}")
            logger.debug(f"=== Received Response Body: {response.text}")

            response.raise_for_status()
            response_data = response.json()
            
            return utils.parse_response(response_data, self.prompt_cost, self.completion_cost)

        except (ValueError, KeyError) as e:
            logger.error("Failed to parse LLM response: %s", e, exc_info=True)
            raise RuntimeError(f"Failed to parse LLM response: {e}")
        except requests.exceptions.RequestException as e:
            # Handle exceptions for network errors, non-200 responses, etc.
            logger.error(f"API request failed: {e}", exc_info=True)
            raise ConnectionError(f"API request failed: {e}")
    
#     def process_stream(self, query, settings, trace):
#         """
#         Processes a query and streams the LLM's response.

#         Args:
#             query (dict): The input query, typically containing a 'messages' list.
#             settings (dict): A dictionary of settings for the API call (e.g., temperature).
#             trace: A tracing object for logging.

#         Yields:
#             dict: Chunks of the response as they are received.

#         Raises:
#             ConnectionError: If the API request fails.
#         """
        
#        # Get credentials from IAM Roles Anywhere
#         logger.info("Getting credentials from IAM Roles Anywhere...")
#         creds = utils.get_credentials(self.certificate_path, self.private_key_path, self.trust_anchor_arn, self.profile_arn, self.base_role_arn, self.region)
        
#         # Create boto3 session with temporary credentials
#         logger.info("Creating boto3 session with temporary credentials...")
#         session = boto3.Session(
#             aws_access_key_id=creds['AccessKeyId'],
#             aws_secret_access_key=creds['SecretAccessKey'],
#             aws_session_token=creds['SessionToken'],
#             region_name=self.region
#         )
        
#         logger.info("Processing streaming request")
#         settings['stream'] = True
#         #headers = utils.create_auth_headers(self.api_key)
#         payload = utils.create_payload_ge_custom_text(self.model, query, settings)

#         try:
#             response = utils.call_api_gateway(session, self.api_gateway_url, "POST", self.region, self.api_key, payload, self.ca_path)
#             response.raise_for_status()
            
#             logger.info("Successfully initiated streaming response from API")
#             yield from utils.process_stream(response, self.prompt_cost, self.completion_cost)

#         except requests.exceptions.RequestException as e:
#             logger.error(f"API streaming request failed: {e}", exc_info=True)
#             raise ConnectionError(f"API request failed: {e}")

class MyEmbeddingModel(AWSGatewayMixin, BaseEmbeddingModel):
    def __init__(self):
        """
        Constructor for the MyEmbeddingModel class.
        """
        self.config = None
        self.plugin_config = None
        self.api_gateway_url = None
        self.api_key = None
        self.model = None
        self.prompt_cost = 0.0
        
        self.certificate_path = None
        self.private_key_path = None
        self.trust_anchor_arn = None
        self.profile_arn = None
        self.base_role_arn = None
        self.target_role_enable = False
        self.target_role_arn = None
        self.region = None
        
    def set_config(self, config: dict, plugin_config: dict) -> None:
        """
        Sets the configuration for the embedding model. This is called by Dataiku.

        Args:
            config (dict): A dictionary of the parameters set by the user in the LLM service settings.
            plugin_config (dict): A dictionary of the plugin-level settings.
        """
        logger.info("Setting configuration for MyEmbeddingModel")
        self._load_common_config(config, plugin_config)
        self._validate_common_config()

    def process(self, query, settings, trace):
        """
        Processes a query and returns the corresponding embedding.

        Args:
            query (dict): The input query to embed. Expects a 'text' key for single-text embedding.
            settings (dict): A dictionary of settings for the API call.
            trace: A tracing object for logging.

        Returns:
            dict: A dictionary containing the embedding vector and optional metadata.

        Raises:
            ValueError: If the input query or API response is malformed.
            ConnectionError: If the API request fails.
        """
        
        session = self._create_aws_session()
            
        logger.info("Processing embedding request")
        text_to_embed = query.get('text')
        if not text_to_embed:
            logger.error("Input query missing 'text' key")
            raise ValueError("Input query for embedding must contain a 'text' key with a string value.")

        logger.debug(f"Creating embedding for text of length: {len(text_to_embed)}")
        
        payload = utils.create_custom_ge_payload_embedding_text(self.model)
        payload['texts'] = [text_to_embed]

        # payload = {
        #     "input": [text_to_embed],
        #     "model": self.model,
        #     "input_type": "query",
        #     "encoding_format": "float",
        #     "truncate": "NONE"
        # }

        try: 
            response = utils.call_api_gateway(session, self.api_gateway_url, "POST", self.region, self.api_key, payload, self.ca_path)
            logger.info(f"Response status code: {response.status_code}")
            logger.debug(f"=== Received Response Body: {response.text}")  

            response.raise_for_status()          
            response_data = response.json()
            
            if not response_data.get('embeddings'):
                logger.error("API response missing valid embedding vector")
                raise ValueError("API response did not contain a valid embedding vector.")
            
            embedding = response_data['embeddings']['float'][0]
            usage = response_data.get('usage', {})
            prompt_tokens = usage.get('prompt_tokens', 0)
            cost = utils.calculate_cost(prompt_tokens, 0, self.prompt_cost, 0)

            logger.info(f"Successfully generated embedding with {prompt_tokens} tokens")
            logger.debug(f"Embedding vector length: {len(embedding)}")

            return {
                "embedding": embedding,
                "promptTokens": prompt_tokens,
                "estimatedCost": cost
            }
        except (ValueError, KeyError, TypeError) as e:
            logger.error("Failed to parse embedding response: %s", e, exc_info=True)
            raise RuntimeError(f"Failed to parse embedding response: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"API request for embedding failed: {e}", exc_info=True)
            raise ConnectionError(f"API request for embedding failed: {e}")
