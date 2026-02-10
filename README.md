 ```
 █████╗  ██████╗  ███████╗ ███╗   ██╗ ████████╗ ██████╗  ██████╗  █████╗  ███╗   ███╗
██╔══██╗ ██╔════╝ ██╔════╝ ████╗  ██║ ╚══██╔══╝ ██╔══██╗ ██╔═══██╗ ██╔══██╗ ████╗ ████║
███████║ ██║  ███╗█████╗   ██╔██╗ ██║    ██║    ██████╔╝ ██║   ██║ ███████║ ██╔████╔██║
██╔══██║ ██║   ██║██╔══╝   ██║╚██╗██║    ██║    ██╔══██╗ ██║   ██║ ██╔══██║ ██║╚██╔╝██║
██║  ██║ ╚██████╔╝███████╗ ██║ ╚████║    ██║    ██║  ██║ ╚██████╔╝ ██║  ██║ ██║ ╚═╝ ██║
╚═╝  ╚═╝  ╚═════╝ ╚══════╝ ╚═╝  ╚═══╝    ╚═╝    ╚═╝  ╚═╝  ╚═════╝  ╚═╝  ╚═╝ ╚═╝     ╚═╝

 ```
Is it possible for multimodal models to navigate in-game worlds?

 Two solutions: 
 1. Runner.py uses Switchbots to physically use navigation sticks on a controller and reach an end-goal.
 2. freeroam_agent uses Python to trigger keyboard presses, controlling an agent on a simulated controller.

Telemetry is tracked via LangFuse. 
setup contains:
- Basic prompts to enable mini-map following, as well as free-roam mode.
- A base '.env' (no tokens, just the setup) to allow you to create your own variants.

Code is provided as is, but happy to answer questions about the solution.
