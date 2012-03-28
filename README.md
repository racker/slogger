slogger - slog through your irc logs
---

1. install twisted (>=12.0.0)

2. download elasticsearch and start it with
    `${ELASTIC_SEARCH_DIR}/bin/elasticsearch`

3. `cp settings.example.py settings.py`

4. `twistd -n -y slogger.py`


Proposed Plan for slogger
-------------------------

Bot will function as a sort of answering machine.  Whenever someone logs on, PMs them saying: "you have X new messages" and maybe displays said messages, based on when the user last existed/entered a room.  Single messages aren't that useful without context, so provide a link to the web interface that gives them a history of all the messages they've missed since they last logged out.

Since a user may be in several channels, the bot should present them with several lists of messages, one for each channel that they were in.

* **TODO** Bot needs a way to keep track of when the user last exited a room or logged out (possible solution: query ES for user entering/exiting channel notifications, and get the latest one for each channel for that user)

* **TODO** Bot needs to be able to fetch all messages directed within a time range (solution: query ES for all messages within a time range)

* **DONE** Web inteface needs to have a URL pointing to a specific query wrt the history of a channel within a time range, so that the bot can link to that URL when a user logs on/joins a room

* **TODO** Bot needs to search all the messages for a channel in the time range the user was not around for messages mentioning the user, but not from the user.  Then it can let the user know the number of messages, or even just print the individual messages if there aren't too many.

* **TODO-MAYBE** Maybe needs to have a list of users that it cares about - if someone has several alts, for example, server maybe should recognize that they are all the same person


**QUESTION** What if the user is still logged in, but not in a channel?  Possibly, the bot should only PM them about a channel they are not in if their name is mentioned in that channel.  Otherwise, only PM them when they log in.

**QUESTION** Should PM/ming a user with missed messages be rate-limited?


Notes about recent Changes and future plans
-------------------------------------------

**WEB**

* *DONE: basic display of some messages*
* *DONE: basic string search*
* *DONE: basic unit tests*
* **TODO**: enable more complicated search
* **TODO**: display messages from flat files as channel history, until I can figure how to fix my issues with search or as a fallback in case ES is down


**BOT**

* *DONE: join multiple rooms*
* *DONE: rotate logs by date*
* *FIXED* - if exactly two results are returned, it is "too large" (<2 >2)
* *FIXED* - needs to register user enter/exit
* **TODO** - add different file logger options so that if an external log rotation tool is used, it's easy to switch which file logger to use
* **TODO** - more unit tests, particularly for the (<2 >2) fix
* **TODO** - change log buffering so that it uses defer.DeferredSemaphore, so that if one write wedges for more than the specified interval time another thread won't be started that writes to the same file.  Maybe each file should be buffered on its own, so one file wedging won't affect another.
* **TODO** - plugin system to parse irc commands
* **TODO** - plugin system for parsing twistd command line args to config the bot/server
* **TODO** - function to parse existing file logs (for backup web interface and for re-indexing ES - e.g. twisted.python.logfile.LogReader)


**SEARCH**

* **QUESTION**: How to query ES with a given range - I do not see it in the client API, besides building a raw query.
* **QUESTION**: Is there a way to change how the channel name field is processed - right now searching for a channel name that starts with '#' doesn't return any results.  When faceting on a channel name, the channel names are returned without the '#'
