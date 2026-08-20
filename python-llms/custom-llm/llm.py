# This file is the implementation of custom LLM ge-custom-sm-llm
from dataiku.llm.python import BaseLLM
from dataiku.llm.python import BaseEmbeddingModel
from dataiku.llm.python import BaseImageGenerationModel

import logging
import requests
import json
from customllm import utils

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

# Create logger
logger = logging.getLogger(__name__)
    
class MyLLM(BaseLLM):
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
        self.config = config
        self.plugin_config = plugin_config
        
        # When using a PRESET, the value is a dictionary
        self.api_gateway_url = config.get('api_keys', {}).get('api_gateway_url')
        self.api_key = config.get('api_keys', {}).get('api_key')
        self.model = config.get('model')
        self.prompt_cost = config.get('prompt_cost', 0.0)
        self.completion_cost = config.get('completion_cost', 0.0)
               
        self.certificate_path = config.get('iam_roles_anywhere',{}).get('certificate_path')
        self.private_key_path = config.get('iam_roles_anywhere', {}).get('private_key_path')
        self.trust_anchor_arn = config.get('iam_roles_anywhere', {}).get('trust_anchor_arn')
        self.profile_arn = config.get('iam_roles_anywhere', {}).get('profile_arn')
        self.base_role_arn = config.get('iam_roles_anywhere', {}).get('base_role_arn')
        self.target_role_enable = config.get('iam_roles_anywhere', {}).get('target_role_enable')
        self.target_role_arn = config.get('iam_roles_anywhere', {}).get('target_role_arn')
        self.region = config.get('iam_roles_anywhere', "ap-southeast-1").get('region')
        self.ca_path = config.get('custom_ca_path', "/data_dataiku_design/ge-cabundle.pem").get('ca_path')
       
        
#         logger.debug(f"Configured API gateway endpoint: {self.api_gateway_url}")
#         logger.debug(f"Configured API Key: {self.api_key}")
#         logger.debug(f"Configured model: {self.model}")
#         logger.debug(f"Configured certificate_path: {self.certificate_path}")
#         logger.debug(f"Configured private_key_path: {self.private_key_path}")
#         logger.debug(f"Configured trust_anchor_arn: {self.trust_anchor_arn}")
#         logger.debug(f"Configured profile_arn: {self.profile_arn}")
#         logger.debug(f"Configured base_role_arn: {self.base_role_arn}")
#         logger.debug(f"Configured target_role_enable: {self.target_role_enable}")
#         logger.debug(f"Configured target_role_arn: {self.target_role_arn}")
#         logger.debug(f"Configured region: {self.region}")
#         logger.debug(f"Configured ca_path: {self.ca_path}")
        

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
        
        # Get credentials from IAM Roles Anywhere
        logger.info("Getting credentials from IAM Roles Anywhere...")
        creds = utils.get_credentials(self.certificate_path, self.private_key_path, self.trust_anchor_arn, self.profile_arn, self.base_role_arn, self.region)
        
        # Create boto3 session with temporary credentials
        logger.info("Creating boto3 session with temporary credentials...")
        base_session = boto3.Session(
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken'],
            region_name=self.region
        )

        if self.target_role_enable:
            target_session = utils.get_assumed_role_session(base_session, self.target_role_arn, self.region)

        logger.info(f"Processing non-streaming request")
        # This method handles non-streaming requests.
        # We explicitly set stream to False in the payload.
        settings['stream'] = False
        #headers = utils.create_auth_headers(self.api_key)
        payload = utils.create_payload_ge_custom_text(self.model, query, settings)
                
        try:
        
            if self.target_role_enable:
                response = utils.call_api_gateway(target_session, self.api_gateway_url, "POST", self.region, self.api_key, payload, self.ca_path)
            else:
                response = utils.call_api_gateway(base_session, self.api_gateway_url, "POST", self.region, self.api_key, payload, self.ca_path)
            
            response.raise_for_status()
            response_data = response.json()
            
            logger.info("Successfully received response from API")
            logger.info(f"Response status code: {response.status_code}")
            logger.debug(f"=== Received Response Body: {response_data}")

            return utils.parse_response(response_data, self.prompt_cost, self.completion_cost)

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

class MyEmbeddingModel(BaseEmbeddingModel):
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
        self.config = config
        self.plugin_config = plugin_config
        self.api_gateway_url = config.get('api_keys', {}).get('api_gateway_url')
        self.api_key = config.get('api_keys', {}).get('api_key')
        self.model = config.get('model')
        self.prompt_cost = config.get('prompt_cost', 0.0)
             
        self.certificate_path = config.get('iam_roles_anywhere',{}).get('certificate_path')
        self.private_key_path = config.get('iam_roles_anywhere', {}).get('private_key_path')
        self.trust_anchor_arn = config.get('iam_roles_anywhere', {}).get('trust_anchor_arn')
        self.profile_arn = config.get('iam_roles_anywhere', {}).get('profile_arn')
        self.base_role_arn = config.get('iam_roles_anywhere', {}).get('base_role_arn')
        self.target_role_enable = config.get('iam_roles_anywhere', {}).get('target_role_enable')
        self.target_role_arn = config.get('iam_roles_anywhere', {}).get('target_role_arn')
        self.region = config.get('iam_roles_anywhere', "ap-southeast-1").get('region')
        self.ca_path = config.get('custom_ca_path', "/data_dataiku_design/ge-cabundle.pem").get('ca_path')

#         logger.debug(f"Configured API gateway endpoint: {self.api_gateway_url}")
#         logger.debug(f"Configured API Key: {self.api_key}")
#         logger.debug(f"Configured model: {self.model}")
#         logger.debug(f"Configured certificate_path: {self.certificate_path}")
#         logger.debug(f"Configured private_key_path: {self.private_key_path}")
#         logger.debug(f"Configured trust_anchor_arn: {self.trust_anchor_arn}")
#         logger.debug(f"Configured profile_arn: {self.profile_arn}")
#         logger.debug(f"Configured base_role_arn: {self.base_role_arn}")
#         logger.debug(f"Configured target_role_enable: {self.target_role_enable}")
#         logger.debug(f"Configured target_role_arn: {self.target_role_arn}")
#         logger.debug(f"Configured region: {self.region}")
#         logger.debug(f"Configured ca_path: {self.ca_path}")

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
        
        # Get credentials from IAM Roles Anywhere
        logger.info("Getting credentials from IAM Roles Anywhere...")
        creds = utils.get_credentials(self.certificate_path, self.private_key_path, self.trust_anchor_arn, self.profile_arn, self.base_role_arn, self.region)
        
        # Create boto3 session with temporary credentials
        logger.info("Creating boto3 session with temporary credentials...")
        base_session = boto3.Session(
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken'],
            region_name=self.region
        )

        if self.target_role_enable:
            target_session = utils.get_assumed_role_session(base_session, self.target_role_arn, self.region)
            
        logger.info("Processing embedding request")
        text_to_embed = query.get('text')
        if not text_to_embed:
            logger.error("Input query missing 'text' key")
            raise ValueError("Input query for embedding must contain a 'text' key with a string value.")

        logger.debug(f"Creating embedding for text of length: {len(text_to_embed)}")
        
        #headers = utils.create_auth_headers(self.api_key)
        payload = {
            "input": [text_to_embed],
            "model": self.model,
            "input_type": "query",
            "encoding_format": "float",
            "truncate": "NONE"
        }

        try: 
            
            if self.target_role_enable:
                response = utils.call_api_gateway(target_session, self.api_gateway_url, "POST", self.region, self.api_key, payload, self.ca_path)
            else:
                response = utils.call_api_gateway(base_session, self.api_gateway_url, "POST", self.region, self.api_key, payload, self.ca_path)
                
            response.raise_for_status()
            response_data = response.json()

            logger.info(f"Response status code: {response.status_code}")
            logger.debug(f"=== Received Response Body: {response_data}")            
            
            if not response_data.get('data') or not response_data['data'][0].get('embedding'):
                logger.error("API response missing valid embedding vector")
                raise ValueError("API response did not contain a valid embedding vector.")
            
            embedding = response_data['data'][0]['embedding']
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
        except requests.exceptions.RequestException as e:
            logger.error(f"API request for embedding failed: {e}", exc_info=True)
            raise ConnectionError(f"API request for embedding failed: {e}")