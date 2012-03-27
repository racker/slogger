# Copyright 2012 Rackspace

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from bot import LogBotFactory
import settings

from twisted.internet import reactor
from twisted.application import internet, service
from twisted.application.service import Application
from twisted.python.filepath import FilePath
from twisted.web import static, server

from web.view import SloggerMainResource

application = Application("Slogger")

root = SloggerMainResource()
path = FilePath(__file__).sibling("web").child("media").path
root.putChild('media', static.File(path))

sc = service.IServiceCollection(application)
site = server.Site(root)
i = internet.TCPServer(8888, site)
i.setServiceParent(sc)

bot_factory = LogBotFactory()
reactor.connectTCP(settings.IRC_HOST, settings.IRC_PORT, bot_factory)
