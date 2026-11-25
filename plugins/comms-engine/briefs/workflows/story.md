# story

Write the story of this run for the stream {stream_name}, as your definition
describes: `scripts/story.py facts`, a short deck in plain words, `story.py
check` (no number the facts lack, nothing on the denylist), `story.py publish`.
When `scripts/theme_words.py status` names themes whose plain words are missing
or out of date, write those too (the `theme-words` skill). A story or theme
words that will not pass their check are reported; nothing waits on them.

Return: `published` (true or false), `cover` (the story's cover line, or an
empty string) and `questions` (how many questions it asks a person).
