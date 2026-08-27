import argparse
import logging
import sys

from ileapp_mcp.server import case_manager, mcp


def main() -> None:
    """CLI entry point for the iLEAPP MCP server."""
    parser = argparse.ArgumentParser(
        prog="ileapp-mcp",
        description="Model Context Protocol (MCP) server for iLEAPP forensic iOS reports",
    )
    parser.add_argument(
        "case_dir",
        nargs="?",
        default=None,
        help="Path to the iLEAPP report output folder (optional, can also be loaded via tool)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging (sent to stderr so stdio is clean)",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.case_dir:
        try:
            case_manager.load_case(args.case_dir)
            sys.stderr.write(f"[iLEAPP-MCP] Loaded initial case directory: {args.case_dir}\n")
        except Exception as e:
            sys.stderr.write(f"[iLEAPP-MCP] Error loading initial case {args.case_dir}: {e}\n")

    if args.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
