"""iLEAPP Model Context Protocol (MCP) Server.

Enables LLMs to explore and analyze iOS Full File System (FFS) forensic reports parsed by iLEAPP.
"""

from ileapp_mcp.case import CaseManager
from ileapp_mcp.server import mcp

__version__ = "0.1.0"
__all__ = ["CaseManager", "mcp", "__version__"]
