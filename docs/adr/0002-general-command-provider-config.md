# General command provider config

SpeakUp should treat the command-backed provider as a general LLM task provider, not as a summarization-only provider. The current `command_summary` config can be reused while pronunciation adaptation is being planned, but it should be renamed to a general `command` provider config so command-backed summarization and pronunciation share one provider identity instead of encoding one task in the provider name.
