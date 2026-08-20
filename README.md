# Python Custom LLM Plugin modified for Great Eastern Life

This project provides a sample custom Large Language Model (LLM) connector for Dataiku DSS, built using the Python LLM framework. The sample is built for the OpenAI API format but can be easily updated to handle different API structures and handling modes. It is designed to connect to any OpenAI-compatible API endpoint, such as the NVIDIA API Catalog, out of the box. 

This has been further customized for Great Eastern Life(GE) to support authentication with IAM Roles Anywhere service to retrieve temporary security credentials that will be used to call into the API Gateway. The AWS setup at GE's requires the plugin to first send requests into the API Gateway backed by Lambda function into SageMaker service. 


## Standard Features 

This plugin supports the core functionalities required for modern LLM applications within Dataiku:

1.  **Chat Completion**: Full support for conversational text generation.
    -   **Streaming**: Responses can be streamed back to the user interface for a real-time experience.
    -   **Tool Calling**: The LLM can invoke tools (e.g., Dataiku Functions or Datasets) as part of its response generation, enabling it to interact with external systems.
    -   **Multimodal Support**: Compatible with Vision Language Models (VLMs) for multimodal chat completion, supporting both text and image inputs (inline base64 images and image URLs).
    -   **Usage Tracking**: Captures token usage (`prompt_tokens`, `completion_tokens`) and calculates the estimated cost for each API call.


2.  **Text Embedding**: Generate vector embeddings for text inputs, which is essential for Retrieval-Augmented Generation (RAG), semantic search, and other NLP tasks.
    -   **Multimodal Embedding**: Supports VLM-based embedding models that can generate embeddings from both text and images.


## IAM Roles Anywhere

1.  **IAM Roles Anywhere**: Added support to authentication with IAM Roles Anywhere
    -   **aws_helper_tool**: This is AWS provided tool to be run in shell to authenticate with IAM Roles Anywhere service. Downloaded from AWS official repo and to be installed on the DSS node. Refer [AWS Website](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html) for more information.
    -   **boto3**: Code-env with boto3 required for this plugin.
    -   **Additions**: Preset parameters added for IAM Roles Anywhere, API Gateway URL and API Key and path to GE's private CA cabundle.pem (needed to verify in request). Two main functions, get_credentials and call_api_gateway added to retrieve temporary security credentials and call the API Gateway with the credentials respectively.


## How It Works

The plugin consists of two main components that integrate with the Dataiku LLM Mesh:

*   `MyLLM`: A class that handles chat completion requests. It transforms Dataiku's native query format into the format expected by OpenAI-compatible APIs, including the specific message structure required for tool calling. It processes both standard and streaming responses.
*   `MyEmbeddingModel`: A class dedicated to handling text embedding requests. It constructs the appropriate payload, calls the embedding endpoint, and returns the vector in a format that Dataiku can use.

Helper functions in `customllm/utils.py` manage API authentication, payload creation, and response parsing.

## Setup and Configuration

Follow these steps to set up and use this custom LLM plugin in your Dataiku DSS instance.

### 1. Installation

-   Zip the contents of this repository.
-   In Dataiku DSS, navigate to **Administration > Plugins > Add Plugin > Upload**.
-   Upload the zipped plugin file.

### 2. Create Presets

There are three presets to populate - (1)API Key, (2)Custom CA Path and (3)IAM Roles Anywhere.

1.  Go to **Plugin > Settings**.
2.  Click **+ Add Preset** for **API Key** and populate the API Gateway's URL and API Key.
3.  Click **+ Add Preset** for **Custom CA Path** and populate the full pathname of the cabundle file on DSS. 
4.  Click **+ Add Preset** for **IAM Roles Anywhere** and populate the necessary parameters. 
5.  Save the preset.

### 3. Configure a Chat/Completion Connection

To use the chat model for text generation:

1.  Go to the LLM Mesh (**from the App launcher, select LLMs**).
2.  Navigate to the **Connections** tab and click **+ New Connection**.
3.  Select **Sample Custom LLM using python** from the list.
4.  Configure the settings:
    -   **Endpoint URL**: The API endpoint for chat completions.
        -   *Example*: `https://integrate.api.nvidia.com/v1/chat/completions`
    -   **Keys preset**: Select the credential preset you created in the previous step.
    -   **Model Key**: The identifier for the model you want to use.
        -   *Example*: `meta/llama-3.1-405b-instruct`
    -   **Prompt Cost / Completion Cost**: (Optional) Enter the cost per 1,000 tokens to enable cost tracking.
5.  Save the connection. You can now use it in your AI-powered components in Dataiku.

### 4. Configure an Embedding Connection

To use the model for generating text embeddings:

1.  In the LLM Mesh, click **+ New Connection**.
2.  Select **Sample Custom LLM using python**.
3.  Configure the settings:
    -   **Endpoint URL**: The API endpoint for embeddings.
        -   *Example*: `https://integrate.api.nvidia.com/v1/embeddings`
    -   **Keys preset**: Select the same credential preset.
    -   **Model Key**: The identifier for the embedding model.
        -   *Example*: `nvidia/nv-embed-v1`
    -   **Prompt Cost**: (Optional) Enter the cost per 1,000 tokens for embeddings.
4.  Save the connection. You can now use it in recipes like "Split & Embed" or in RAG agents.

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

*   **Message Transformation**: The `create_payload` function in `utils.py` is crucial for tool-calling compatibility. It transforms the `toolCalls` and `toolOutputs` from Dataiku's format into the `tool_calls` and `tool_call_id` format expected by many OpenAI-compatible APIs.
*   **Multimodal Message Handling**: The plugin automatically detects and transforms Dataiku's `parts` format (containing `TEXT`, `IMAGE_INLINE`, and `IMAGE_URL` types) into OpenAI's multimodal content format, enabling seamless integration with Vision Language Models (VLMs).
*   **Streaming Logic**: The `process_stream` function handles Server-Sent Events (SSE) from the API, parsing `data:` lines and yielding structured chunks (text, tool calls, or metadata) that the Dataiku framework can understand.
*   **Logging**: Comprehensive logging has been implemented throughout the codebase using Python's standard `logging` module, providing detailed insights at INFO, DEBUG, WARNING, and ERROR levels for monitoring and troubleshooting.
*   **Error Handling**: The code includes basic error handling for API requests and malformed responses to ensure stability.
