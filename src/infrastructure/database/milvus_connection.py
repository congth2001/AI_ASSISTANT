"""
Milvus Vector Database Client - Direct implementation for Milvus vector database operations.
"""

import logging
import os
from typing import List, Dict, Any, Optional, Union, Tuple
import time
from src.infrastructure.utils.logger import get_logger
from src.infrastructure.utils.singleton.singleton import Singleton

# logger = logging.getLogger(__name__)
logger = get_logger("milvus connection")


class MilvusClient(metaclass=Singleton):
    """
    Milvus-specific implementation for vector database operations.
    Provides methods to interact with Milvus vector database.
    """
    
    def __init__(self):
        pass
    
    def init_app(self, config: Dict):
        """
        Initialize the Milvus client.
        
        Args:
            host: Milvus server host
            port: Milvus server port
            alias: Connection alias for Milvus
        """
        self.host = config["milvus"]["host"]
        self.port = config["milvus"]["port"]
        self.alias = config["milvus"]["alias"]
        self.connected = False
    
    def connect(self) -> bool:
        """
        Connect to Milvus server.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            from pymilvus import connections
            
            # Connect to Milvus server
            connections.connect(
                alias=self.alias,
                host=self.host,
                port=self.port
            )
            
            self.connected = True
            logger.info(f"Connected to Milvus server at {self.host}:{self.port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}", exc_info=True)
            self.connected = False
            return False
    
    def disconnect(self) -> bool:
        """
        Disconnect from Milvus server.
        
        Returns:
            bool: True if disconnection successful, False otherwise
        """
        try:
            from pymilvus import connections
            
            connections.disconnect(self.alias)
            self.connected = False
            logger.info(f"Disconnected from Milvus server (alias: {self.alias})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to disconnect from Milvus: {e}", exc_info=True)
            return False

    def has_collection(self, collection_name: str) -> bool:
        """
        Check if a collection exists in Milvus.
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            bool: True if collection exists, False otherwise
        """
        try:
            from pymilvus import utility
            
            return utility.has_collection(collection_name, using=self.alias)
            
        except Exception as e:
            logger.error(f"Error checking collection existence: {e}", exc_info=True)
            return False

    def get_collection_info(self, collection_name: str) -> Dict[str, Any]:
        """
        Get information about a collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Dict[str, Any]: Collection information
        """
        try:
            from pymilvus import Collection
            
            if not self.has_collection(collection_name):
                return {"exists": False}
                
            collection = Collection(name=collection_name, using=self.alias)
            
            info = {
                "exists": True,
                "name": collection.name,
                "description": collection.description,
                "schema": str(collection.schema),
                "num_entities": collection.num_entities
            }
            
            return info
            
        except Exception as e:
            logger.error(f"Failed to get info for collection {collection_name}: {e}", exc_info=True)
            return {"exists": False, "error": str(e)}

milvus_client = MilvusClient()
