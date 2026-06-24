# Separate runtime state store for now

SpeakUp will keep session state in a separate local runtime store for now, rather than adding mutable session tables to notification history. Notification history answers what happened and supports replay, while session state answers what SpeakUp currently knows about an agent session; keeping them separate makes the new behavior easier to evolve. The intended direction is to eventually consolidate SpeakUp's local runtime data into one database once the session state model has settled and the migration boundary is clear.
