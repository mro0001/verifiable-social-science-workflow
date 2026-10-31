"""The MCP servers, which expose the databases to the harness and the model.

Appendix A2.2 says MCP servers expose the databases to the harness and the
model through the Model Context Protocol, and Figure A2 draws them beside the
harness and the databases. protocol.py speaks the protocol over standard
input and output with the standard library (Track D choice 8), and each
server gives its tools to it.
"""
