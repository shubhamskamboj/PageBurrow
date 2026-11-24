"""The table of tools: name -> function(files, options) -> Result."""
TOOLS = {}


def tool(name):
    def register(function):
        TOOLS[name] = function
        return function
    return register
