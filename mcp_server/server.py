"""Server MCP della piattaforma di ticketing (trasporto stdio)."""
from mcp.server.mcpserver import MCPServer

from .tools import TOOLS

ISTRUZIONI = (
    "Strumenti di back-office per operatori di una piattaforma di ticketing (dati sintetici). "
    "Gli importi sono in centesimi di euro. I tool di scrittura modificano i dati."
)


def crea_server() -> MCPServer:
    server = MCPServer("backoffice-ticketing", instructions=ISTRUZIONI)
    for tool in TOOLS:
        server.add_tool(
            tool.esegui,
            name=tool.NOME,
            description=tool.DESCRIZIONE,
            annotations=tool.ANNOTAZIONI,
            structured_output=True,
        )
    return server


def main() -> None:
    # stdout e' il canale del protocollo: nessuna print() va scritta li'.
    crea_server().run(transport="stdio")


if __name__ == "__main__":
    main()
