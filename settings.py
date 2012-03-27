DEBUG = False

########################
# IRC NETWORK SETTINGS #
########################
NICK = 'test_slogger_nick'
ALT_NICK = '_test_slogger_nick'
IRC_HOST = 'irc.freenode.net'
IRC_PORT = 6667
IRC_CHANNELS = ['##test_slogger_room', '##test_slogger_room2']

####################
# LOGGING SETTINGS #
####################
LOG_FILE_PATH = './logs/'
ELASTICSEARCH_HOSTS = ['localhost:9200']
ELASTICSEARCH_TIMEOUT = 10

###########################
# HTTP INTERFACE SETTINGS #
###########################
ENABLE_HTTP = True
HTTP_HOST = '127.0.0.1'
HTTP_PORT = 8087
