from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DiagnosticSkills")


@mcp.tool()
def ping_hardware(device_ip: str) -> str:
    print(f"Pinging {device_ip}...")
    return f"{device_ip} is online"


if __name__ == "__main__":
    print("Starting MCP Server...")
    mcp.run()