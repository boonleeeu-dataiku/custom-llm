# Python Custom LLM Plugin modified for Great Eastern Life

This project provides a custom Large Language Model (LLM) connector for Dataiku DSS, built using the Python LLM framework. While the original sample was designed for OpenAI-compatible APIs, this implementation has been customized for Great Eastern Life (GE) to route requests through an AWS API Gateway endpoint protected with IAM Roles Anywhere and SigV4 signing.

In GE's setup, the plugin first obtains temporary AWS credentials using IAM Roles Anywhere, optionally assumes a target role, signs the request to API Gateway, and then sends the payload to the backend service backed by Lambda and SageMaker.


## Standard Features 

This plugin supports the core functionalities required for modern LLM applications within Dataiku:

1.  **Chat Completion**: Full support for conversational text generation.
    -   **Tool Calling**: The LLM can invoke tools (e.g., Dataiku Functions or Datasets) as part of its response generation, enabling it to interact with external systems.
    -   **Multimodal Support**: Compatible with Vision Language Models (VLMs) for multimodal chat completion, supporting both text and image inputs (inline base64 images and image URLs).
    -   **Usage Tracking**: Captures token usage (`prompt_tokens`, `completion_tokens`) and calculates the estimated cost for each API call.
    -   **GE Custom Payload Format**: Transforms Dataiku messages into the request structure expected by GE's API Gateway backend.


2.  **Text Embedding**: Generate vector embeddings for text inputs, which is essential for Retrieval-Augmented Generation (RAG), semantic search, and other NLP tasks.
    -   **Usage Tracking**: Captures prompt token usage and calculates the estimated cost for embedding requests.


## IAM Roles Anywhere

1.  **IAM Roles Anywhere**: Added support to authentication with IAM Roles Anywhere
    -   **aws_signing_helper**: AWS-provided command line helper used to authenticate with IAM Roles Anywhere and retrieve temporary credentials. It must be installed on the DSS node and available on `PATH`. Refer [AWS Website](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html) for more information.
    -   **boto3**: Required in the plugin code environment to create AWS sessions and optionally assume a target role.
    -   **Additions**: Preset parameters added for IAM Roles Anywhere, API Gateway URL and API Key, and the path to GE's private CA bundle used for TLS verification. The helper functions `get_credentials`, `get_assumed_role_session`, and `call_api_gateway` handle credential retrieval, optional role assumption, and signed API Gateway calls.


## How It Works

The plugin consists of two main components that integrate with the Dataiku LLM Mesh:

*   `MyLLM`: A class that handles chat completion requests. It validates the configured presets, creates an AWS session from IAM Roles Anywhere credentials, transforms Dataiku's native query format into the format expected by GE's backend, and parses the response into the structure expected by Dataiku.
*   `MyEmbeddingModel`: A class dedicated to handling text embedding requests. It uses the same authentication flow, sends a text embedding payload to the backend endpoint, and returns the vector in a format that Dataiku can use.

Helper functions in `customllm/utils.py` manage credential retrieval, SigV4 request signing, payload creation, response parsing, cost calculation, and multimodal message conversion.

## Setup and Configuration

Follow these steps to set up and use this custom LLM plugin in your Dataiku DSS instance.

### 1. Installation

-   Build the zip from a release tag, e.g. `git archive --format=zip -o custom-llm-1.3.2.zip v1.3.2` (see [Versioning & Releases](#versioning--releases)).
-   In Dataiku DSS, navigate to **Administration > Plugins > Add Plugin > Upload**.
-   Upload the zipped plugin file.
-   Ensure the `aws_signing_helper` binary is installed on the DSS node and available to the DSS process.

### 2. Create Presets

There are three presets to populate - (1)API Key, (2)Custom CA Path and (3)IAM Roles Anywhere.

1.  Go to **Plugin > Settings**.
2.  Click **+ Add Preset** for **API Key** and populate the API Gateway URL and API Key.
3.  Click **+ Add Preset** for **Custom CA Path** and populate the full pathname of the CA bundle file on DSS. If left blank, the plugin defaults to `/data_dataiku_design/ge-cabundle.pem`.
4.  Click **+ Add Preset** for **IAM Roles Anywhere** and populate the certificate path, private key path, trust anchor ARN, profile ARN, base role ARN, and region.
5.  If cross-account access is required, enable **Assume Target Role** and populate the **Target Role ARN**.
6.  Save the preset.

### 3. Configure a Chat/Completion Connection

To use the chat model for text generation:

1.  Go to the LLM Mesh (**from the App launcher, select LLMs**).
2.  Navigate to the **Connections** tab and click **+ New Connection**.
3.  Select **Sample Custom LLM using python** from the list.
4.  Configure the settings:
    -   **IAM Roles Anywhere preset**: Select the IAM Roles Anywhere preset you created in the previous step.
    -   **API Key preset**: Select the API Gateway preset you created in the previous step.
    -   **Custom CA Path preset**: Select the CA path preset if TLS verification requires a private CA bundle.
    -   **Model Key**: The identifier for the model that the backend service should use.
        -   *Example*: `openai/gpt-oss-20b`
    -   **Prompt Cost / Completion Cost**: (Optional) Enter the cost per 1,000 tokens to enable cost tracking.
5.  Save the connection. You can now use it in your AI-powered components in Dataiku.

### 4. Configure an Embedding Connection

To use the model for generating text embeddings:

1.  In the LLM Mesh, click **+ New Connection**.
2.  Select **Sample Custom LLM using python**.
3.  Configure the settings:
    -   **IAM Roles Anywhere preset**: Select the IAM Roles Anywhere preset.
    -   **API Key preset**: Select the API Gateway preset.
    -   **Custom CA Path preset**: Select the CA path preset if required.
    -   **Model Key**: The identifier for the embedding model exposed by the backend service.
    -   **Prompt Cost**: (Optional) Enter the cost per 1,000 tokens for embeddings.
4.  Save the connection. You can now use it in recipes like "Split & Embed" or in RAG agents.

## Versioning & Releases

Releases follow [Semantic Versioning](https://semver.org/). The version in `plugin.json` must match the git tag `vX.Y.Z`.

*   **Develop on `main`** using short-lived feature branches and PRs.
*   **Release**: bump `version` in `plugin.json`, commit, then `git tag -a vX.Y.Z -m "X.Y.Z" && git push origin vX.Y.Z`.
*   **Patch an older release**: create `release/X.Y` from the tag only when needed (`git switch -c release/1.3 v1.3.2`), cherry-pick the fix with `git cherry-pick -x <sha>`, bump the patch version, and tag it (e.g. `v1.3.3`).
*   **Deploy a specific version**: `git archive --format=zip -o custom-llm-X.Y.Z.zip vX.Y.Z` and upload the zip in DSS. `.gitattributes` keeps `state.json` (DSS-generated) out of the zip.

| Environment | Plugin version |
|---|---|
| dev | _fill in_ |
| uat | _fill in_ |
| prod | _fill in_ |

## Project Structure

```
├── code-env/
│   └── python/
│       └── spec                  
│           └── requirements.txt  # boto3 requirement for code-env
├── parameter-sets/
│   └── api-credentials/
│       └── parameter-set.json    # Defines the API Gateway URL and API key credential preset.
│   └── custom-ca-path/
│       └── parameter-set.json    # Defines the full pathname of cabundle.pem preset.
│   └── iam-roles-anywhere/
│       └── parameter-set.json    # Defines the IAM Roles Anywhere parameters preset.
├── python-llms/
│   └── custom-llm/
│       ├── llm.py                # Main implementation of the LLM and Embedding classes.
│       └── llm.json              # Descriptor for the LLM connection parameters.
├── python-lib/
│   └── customllm/
│       └── utils.py              # Helper functions for auth, payload creation, and parsing.
├── plugin.json                   # Core plugin metadata.
└── README.md                     # This file.
```

## Development Notes

*   **Shared Configuration Flow**: `AWSGatewayMixin` centralizes preset loading, validation, and AWS session creation for both chat and embedding requests.
*   **Message Transformation**: The `create_payload_ge_custom_text` function in `utils.py` transforms the `toolCalls` and `toolOutputs` from Dataiku's format into the `tool_calls` and `tool_call_id` format expected by the backend service.
*   **Multimodal Message Handling**: The plugin automatically detects and transforms Dataiku's `parts` format (containing `TEXT`, `IMAGE_INLINE`, and `IMAGE_URL` types) into OpenAI's multimodal content format, enabling seamless integration with Vision Language Models (VLMs).
*   **AWS Authentication**: Requests are signed using `SigV4Auth` for the `execute-api` service, and the API key is added as an `x-api-key` header before the request is sent.
*   **Optional Role Assumption**: When enabled, the plugin first authenticates with a base role through IAM Roles Anywhere and then assumes a target role using STS.
*   **Response Parsing**: The plugin supports both a GE gateway response format containing `body.model_output.generated_text` and a more OpenAI-like response format containing `choices[0].message`.
*   **Streaming Logic**: Streaming helper code is retained in comments for reference, but the active implementation currently uses non-streaming requests only.
*   **Logging**: Comprehensive logging has been implemented throughout the codebase using Python's standard `logging` module, providing detailed insights at INFO, DEBUG, WARNING, and ERROR levels for monitoring and troubleshooting.
*   **Error Handling**: The code includes basic error handling for API requests and malformed responses to ensure stability.
