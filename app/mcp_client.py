import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def call_mcp_tool(tool_name: str, args: dict) -> str:
    """Spins up the FastMCP server as a subprocess and executes the tool."""
    
    # Resolve absolute path to the local mcp_server.py
    base_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_server_path = os.path.join(base_dir, "mcp_server.py")

    server_params = StdioServerParameters(
        command="python3",
        args=[mcp_server_path]
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=args)
                # Extract and return the physical string returned by the tool
                return result.content[0].text
    except Exception as e:
        raise Exception(f"MCP subprocess failed: {str(e)}")