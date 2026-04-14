# NVIDIA NIM and MCP Integration

## Important Rule

NVIDIA NIM is not the MCP server.

Instaply should use:

- MCP for tool exposure
- NVIDIA NIM for reasoning and tool-call selection
- Instaply services and workers for real execution

## Correct Flow

1. user talks to Claude/Desktop or ChatGPT
2. the client talks to Instaply MCP
3. Instaply MCP exposes tools such as:
   - search jobs
   - rank jobs
   - generate packet
   - plan application
   - run supported apply
4. Instaply sends those tool schemas to NVIDIA NIM using chat completions
5. NVIDIA NIM returns tool calls
6. Instaply executes them
7. Instaply returns results to the model and the user

## Why This Matters

This gives you:

- privacy
- auditability
- control over execution
- the ability to swap model providers later

## What NIM Should Handle

- JD parsing
- answer selection
- ranking assistance
- writing
- agent planning

## What Instaply Should Handle

- auth
- MCP
- business logic
- browser automation
- application submission rules
- evidence capture
- billing and credits

## Deployment Note

Start with hosted NIM endpoints first.

Only consider self-hosting NIM later if:

- cost justifies it
- you need tighter control
- you can handle GPU infrastructure

## Product Positioning Note

Instaply should be described as:

- an MCP-native private job application agent
- powered by NVIDIA NIM for reasoning
- executed by Instaply services and workers

That is cleaner and more accurate than saying NIM "runs the whole product."

