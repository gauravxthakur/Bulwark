import os
from dotenv import load_dotenv
from langchain_mcp_adapters import MultiServerMCPClient

load_dotenv()

class MCPManager():
    
    def __init__(self):
        self.client = MultiServerMCPClient()
        self.mongodb_uri = os.getenv("MONGO_URI")
        
    async def connect_mongo(self):
        """ Connects to the MongoDB MCP Server and returns discovered tools."""
        if not self.mongodb_uri:
            raise ValueError("MONGO_URI not found in environment variables.")
        print(f"Connecting to MongoDB MCP Server at {self.mongodb_uri}")
        
        try:
            await self.client.connect_to_server(
                "mongodb_server",
                command="npx",
                args=[
                    "-y", 
                    "mongodb-mcp-server@latest", 
                    self.mongodb_uri
                ]
            )
            
            # Fetch the dynamic tools defined by the MongoDB MCP Server
            mongo_tools = self.client.get_tools()
            print(f"[MCP] Successfully connected. Discovered {len(mongo_tools)} MongoDB tools.")
            return mongo_tools
        
        except Exception as e:
            print(f"[MCP ERROR] Failed to connect to MongoDB Server: {e}")
            return []
        
        
    async def disconnect_all(self):
        """
        Gracefully close all MCP server connections and stop subprocesses.
        """
        if self.client:
            print("[MCP] Shutting down all MCP connections...")
            try:
                # This kills the 'npx' subprocesses and closes the communication pipes
                await self.client.close() 
                print("[MCP] Shutdown complete.")
            except Exception as e:
                print(f"[MCP ERROR] Error during shutdown: {e}")