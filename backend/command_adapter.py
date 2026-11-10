def prepare_node_commands(pipeline_plan: dict):
    supported_commands = []
    review_commands = []

    allowed_commands = {"npm install", "npm run build"}

    all_commands = pipeline_plan["install_commands"] + pipeline_plan["build_commands"]

    for command in all_commands:
        if command in allowed_commands:
            supported_commands.append(command)
        else:
            review_commands.append(command)

    return {
        "supported_commands": supported_commands,
        "review_commands": review_commands,
    }
