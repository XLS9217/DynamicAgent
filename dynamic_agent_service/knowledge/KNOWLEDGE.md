there will be 
a "blueprint"
    which will be the idea of a "thing" like a car
and there will be "knowledge_node"
    which will be the idea of attributes for the blueprint, like information of wheels and engine of the car

we make a blueprint first with a query of what it might be use for or might have
    the agent will figure out what attribtue it needs

we then inbound big chunk of text
    agent will figure out what attribute to add
    and generate text to that attribute which is the knowledge_node

when we query,
    we get the knowledge_node, find out what blueprint it's in
    we pull out the structure of the blueprint with fetched knowledge_node, 
    for unfetched, leave a id to later get it

when the agent is answering the question,
    if the agent needs more information, it will use the id to get the rest of knowledge node 



terms
- knowledge text is what we create from input data


