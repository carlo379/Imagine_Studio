"""Known reviewed prompts for transport-only tests; never contacts a writer."""
def reviewed_prompt(app,kind,record):
    stored=app.prompting.record(kind,record['id'])
    context=app.prompting.context(kind,stored,{})
    return app.prompting.mark(kind,stored,context,'reviewed-test-fixture','fixture-writer')
