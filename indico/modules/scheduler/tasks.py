# -*- coding: utf-8 -*-
##
##
## This file is part of CDS Indico.
## Copyright (C) 2002, 2003, 2004, 2005, 2006, 2007 CERN.
##
## CDS Indico is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of the
## License, or (at your option) any later version.
##
## CDS Indico is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with CDS Indico; if not, write to the Free Software Foundation, Inc.,
## 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

import copy
import logging
import time

from datetime import timedelta
from pytz import timezone
from pytz import common_timezones

# Required by specific tasks
from MaKaC.user import Avatar
from MaKaC.i18n import _
from MaKaC.common.Configuration import Config
from MaKaC.common.info import HelperMaKaCInfo
from MaKaC.common.Counter import Counter
# end required

import ZODB
from persistent import Persistent

from indico.util.fossilize import fossilizes, Fossilizable
from indico.util.date_time import nowutc, int_timestamp
from indico.modules.scheduler.fossils import ITaskFossil
from indico.modules.scheduler import base

"""
Defines base classes for tasks, and some specific tasks as well
"""


class BaseTask(Persistent, Fossilizable):
    """
    To create a new Task subclass Task and define a _run() method with
    the tasks' actions

    Description of each attribute:
    AUTOMATIC ATTRS:
    - startedOn:  actual date the task started running
    - endedOn:    actual date the task's run method finished
    - running:    True or False depending on what the task thinks it's happening

    USER-CONFIGURABLE ATTRS (through kw arguments to init and setters/getters)
    - startOn:    time at which the task creator wanted the task to start (can be blank)
    - endOn:      last point in time where the task can run. A task will never enter the
                  runningQueue if current time is past endOn
    """

    fossilizes(ITaskFossil)

    def __init__(self, **kwargs):
        self.createdOn = nowutc()
        self.typeId = self.__class__.__name__
        self.reset(**kwargs)

    def reset(self, **kwargs):
        '''Resets a task to its state before being run'''

        self.startedOn = None
        self.endedOn = None
        self.running = False
        self.onRunningListSince = None
        self.startOn = None
        self.endOn = None
        self.status = base.TASK_STATUS_NONE
        self.id = None

        for k in ('startOn', 'endOn'):
            if k in kwargs:
                setattr(self, k, kwargs[k])

    def getEndOn(self):
        return self.EndOn

    def getStartOn(self):
        return self.startOn

    def getCreatedOn(self):
        return self.createdOn

    def setStartOn(self, newtime):
        self.startOn = newtime

    def setEndOn(self, newtime):
        self.endOn = newtime

    def setOnRunningListSince(self, sometime):
        self.onRunningListSince = sometime
        self._p_changed = 1

    def setStatus(self, newstatus):
        self.status = base.TASK_STATUS_QUEUED

    def getOnRunningListSince(self):
        return self.onRunningListSince

    def getId(self):
        return self.id

    def getTypeId(self):
        return self.typeId

    def initialize(self, newid, newstatus):
        self.id = newid
        self.status = newstatus

    def isPeriodic(self):
        return False

    def isPeriodicUnique(self):
        return False

    def getStartedOn(self):
        return self.startedOn

    def getEndedOn(self):
        return self.endedOn

    def plugLogger(self, logger):
        self._v_logger = logger

    def getLogger(self):
        if not getattr(self, '_v_logger') or not self._v_logger:
            self._v_logger = logging.getLogger('task/%s' % self.typeId)
        return self._v_logger

    def start(self):

        tsDiff = int_timestamp(nowutc()) - int_timestamp(self.startOn)

        if tsDiff < 0:
            self.getLogger().debug('Task %s will wait for some time. (%s) > (%s)' % (self.id, self.startOn, nowutc()))
            time.sleep(tsDiff)

        if self.endOn and nowutc() > self.endOn:
            self.getLogger().warning('Task %s will not be executed, endOn (%s) < current time (%s)' % (self.id, self.endOn, nowutc()))
            return False

        self.startedOn = nowutc()
        self.running = True
        self.status = base.TASK_STATUS_RUNNING
        self.run()
        self.running = False
        self.endedOn = nowutc()


    def tearDown(self):
        '''If a task needs to do something once it has run and been removed from runningList
        overload this method'''
        pass

    def __str__(self):
        return "<%s %s %s %s>" % (self.typeId, self.id, self.status, self.startOn)


class OneShotTask(BaseTask):
    '''Tasks that are executed only once'''
    def __init__(self, **kwargs):
        super(OneShotTask, self).__init__(**kwargs)
        if 'runOn' in kwargs:
            self.runOn = kwargs['runOn']
        else:
            self.runOn = nowutc()


    def getRunOn(self):
        return self.runOn


class PeriodicTask(BaseTask):
    """
    Tasks that should be executed at regular intervals
    """

    def __init__(self, **kwargs):
        """
        Must be fed:
        - interval: seconds between each successive run
        """
        super(PeriodicTask, self).__init__(**kwargs)
        if 'interval' not in kwargs:
            raise Exception('Error: PeriodicTask was not given an interval')

        self.interval = kwargs['interval']


    def isPeriodic(self):
        return True

    def getInterval(self):
        return self.interval

    def start(self):
        super(PeriodicTask, self).start()

    def tearDown(self):
        super(PeriodicTask, self).tearDown()
        # precision of seconds, don't use this for real time response systems

        # We reinject ourselves into the Queue
        self.reset()


class PeriodicUniqueTask(PeriodicTask):
    '''Singleton periodic tasks: no two or more PeriodicUniqueTask of this
    class will be queued or running at the same time'''
    def __init__(self, **kwargs):
        super(PeriodicUniqueTask, self).__init__(**kwargs)

    def isPeriodicUnique(self):
        return True


class CategoryStatisticsUpdaterTask(PeriodicUniqueTask):
    '''Updates statistics associated with categories
    '''
    def __init__(self, cat, **kwargs):
        super(CategoryStatisticsUpdaterTask, self).__init__(**kwargs)
        self._cat = cat

    def run(self):
        from MaKaC.statistics import CategoryStatistics
        CategoryStatistics.updateStatistics(self._cat)


# TODO CERN Specific
class FoundationSyncTask(PeriodicUniqueTask):
    """
    Synchronizes room data (along with associated room managers
    and equipment) with Foundation database.

    Also, updates list of CERN Official Holidays

    (This is object for a task class)
    """
    def __init__(self, **kwargs):
        super(FoundationSyncTask, self).__init__(**kwargs)
        obj.__init__(self)

    def run(self):
        from MaKaC.common.FoundationSync.foundationSync import FoundationSync
        FoundationSync().doAll()



class SendMailTask(OneShotTask):
    """
    """
    def __init__(self, **kwargs):
        super(SendMailTask, self).__init__(**kwargs)
        self.fromAddr = ""
        self.toAddr = []
        self.toUser = []
        self.ccAddr = []
        self.subject = ""
        self.text = ""
        self.smtpServer = Config.getInstance().getSmtpServer()

    def run(self):
        import smtplib
        from MaKaC.webinterface.mail import GenericMailer, GenericNotification

        addrs = [smtplib.quoteaddr(x) for x in self.toAddr]
        ccaddrs = [smtplib.quoteaddr(x) for x in self.ccAddr]

        for user in self.toUser:
            addrs.append(smtplib.quoteaddr(user.getEmail()))

        GenericMailer.send(GenericNotification({"fromAddr": self.fromAddr,
                                                "toList": addrs,
                                                "ccList": ccaddrs,
                                                "subject": self.subject,
                                                "body": self.text }))

    def getConference(self):
        return self.conf

    def setFromAddr(self, addr):
        self.fromAddr = addr
        self._p_changed = 1

    def getFromAddr(self):
        return self.fromAddr

    def initialiseToAddr( self ):
        self.toAddr = []
        self._p_changed=1

    def addToAddr(self, addr):
        if not addr in self.toAddr:
            self.toAddr.append(addr)
            self._p_changed=1

    def addCcAddr(self, addr):
        if not addr in self.ccAddr:
            self.ccAddr.append(addr)
            self._p_changed=1

    def removeToAddr(self, addr):
        if addr in self.toAddr:
            self.toAddr.remove(addr)
            self._p_changed=1

    def setToAddrList(self, addrList):
        """Params: addrList -- addresses of type : list of str."""
        self.toAddr = addrList
        self._p_changed=1

    def getToAddrList(self):
        return self.toAddr

    def setCcAddrList(self, addrList):
        """Params: addrList -- addresses of type : list of str."""
        self.ccAddr = addrList
        self._p_changed=1

    def getCcAddrList(self):
        return self.ccAddr

    def addToUser(self, user):
        if not user in self.toUser:
            self.toUser.append(user)
            self._p_changed=1

    def removeToUser(self, user):
        if user in self.toUser:
            self.toUser.remove(user)
            self._p_changed=1

    def getToUserList(self):
        return self.toUser

    def setSubject(self, subject):
        self.subject = subject

    def getSubject(self):
        return self.subject

    def setText(self, text):
        self.text = text

    def getText(self):
        return self.text



class AlarmTask(SendMailTask):
    """
    implement an alarm componment
    """
    def __init__(self, conf, **kwargs):
        super(AlarmTask, self).__init__(**kwargs)
        self.conf = conf
        self.timeBefore = None
        self.text = ""
        self.note = ""
        self.confSumary = False
        self.toAllParticipants = False

    def getToAllParticipants(self):
        try:
            return self.toAllParticipants
        except:
            self.toAllParticipants = False
            return self.toAllParticipants

    def setToAllParticipants(self, toAllParticipants):
        self.toAllParticipants = toAllParticipants

    def clone(self, conference):
        alarm = AlarmTask(conference)
        alarm.initialiseToAddr()
        for addr in self.getToAddrList():
            alarm.addToAddr(addr)
        alarm.setFromAddr(self.getFromAddr())
        alarm.setSubject(self.getSubject())
        alarm.setConfSumary(self.getConfSumary())
        alarm.setNote(self.getNote())
        alarm.setText(self.getText())
        if self.getTimeBefore():
            alarm.setTimeBefore(copy.copy(self.getTimeBefore()))
        else:
            alarm.setStartDate(copy.copy(self.getStartDate()))
        alarm.setToAllParticipants(self.getToAllParticipants())
        return alarm

    def getStartDate(self):
        if self.timeBefore:
            return self.conf.getStartDate() - self.timeBefore
        else:
            return task.getStartDate(self)

    def getAdjustedStartDate(self,tz=None):
        if not tz:
            tz = self.conf.getTimezone()
        if tz not in common_timezones:
           tz = 'UTC'
        if self.timeBefore:
            return self.conf.getStartDate().astimezone(timezone(tz)) - self.timeBefore
        else:
            if task.getStartDate(self):
                return task.getStartDate(self).astimezone(timezone(tz))
            return None
        if self.getStartDate():
            return self.getStartDate().astimezone(timezone(tz))
        return None

    def setTimeBefore(self, timeDelta):
        #we don't need startDate if timeBefore is set
        self.timeBefore = timeDelta
        self.startDate = None
        self._p_changed=1

    def getTimeBefore(self):
        return self.timeBefore

    def addToUser(self, user):
        super(AlarmTask, self).addToUser(user)
        if isinstance(user, Avatar):
            user.linkTo(self, "to")

    def removeToUser(self, user):
        super(AlarmTask, self).removeToUser(user)
        if isinstance(user, Avatar):
            user.unlinkTo(self, "to")

    def getText(self):
        return self.text

    def getLocator(self):
        d = self.conf.getLocator()
        d["alarmId"] = self.getId()
        return d

    def canAccess(self, aw):
        return self.conf.canAccess(aw)

    def canModify(self, aw):
        return self.conf.canModify(aw)

    def _setMailText(self):
        text = self.text
        if self.note:
            text = text + "Note: %s" % self.note
        if self.confSumary:
            #try:
                from MaKaC.common.output import outputGenerator
                from MaKaC.accessControl import AdminList, AccessWrapper
                import MaKaC.webinterface.urlHandlers as urlHandlers
                admin = AdminList().getInstance().getList()[0]
                aw = AccessWrapper()
                aw.setUser(admin)
                path = Config.getInstance().getStylesheetsDir()
                if os.path.exists("%s/text.xsl" % path):
                    stylepath = "%s/text.xsl" % path
                outGen = outputGenerator(aw)
                vars = { \
                        "modifyURL": urlHandlers.UHConferenceModification.getURL( self.conf ), \
                        "sessionModifyURLGen": urlHandlers.UHSessionModification.getURL, \
                        "contribModifyURLGen": urlHandlers.UHContributionModification.getURL, \
                        "subContribModifyURLGen":  urlHandlers.UHSubContribModification.getURL, \
                        "materialURLGen": urlHandlers.UHMaterialDisplay.getURL, \
                        "resourceURLGen": urlHandlers.UHFileAccess.getURL }
                confText = outGen.getOutput(self.conf,stylepath,vars)
                text += "\n\n\n" + confText
            #except:
            #    text += "\n\n\nSorry could not embed text version of the agenda..."
        super(AlarmTask, self).setText(text)

    def setNote(self, note):
        self.note = note
        self._setMailText()
        self._p_changed=1

    def getNote(self):
        return self.note

    def setConfSumary(self, val):
        self.confSumary = val
        self._setMailText()
        self._p_changed=1

    def getConfSumary(self):
        return self.confSumary

    def run(self):

        # Date checkings...
        from MaKaC.conference import ConferenceHolder
        from MaKaC.common.timezoneUtils import nowutc
        if not ConferenceHolder().hasKey(self.conf.getId()) or \
                self.conf.getStartDate() <= nowutc():
           self.conf.removeAlarm(self)
           return True
        # Email
        self.setSubject("Event reminder: %s"%self.conf.getTitle())
        try:
            locationText = self.conf.getLocation().getName()
            if self.conf.getLocation().getAddress() != "":
                locationText += ", %s" % self.conf.getLocation().getAddress()
            if self.conf.getRoom().getName() != "":
                locationText += " (%s)" % self.conf.getRoom().getName()
        except:
            locationText = ""
        if locationText != "":
            locationText = _(""" _("Location"): %s""") % locationText

        if self.getToAllParticipants() :
            for p in self.conf.getParticipation().getParticipantList():
                self.addToUser(p)

        from MaKaC.webinterface import urlHandlers
        if Config.getInstance().getShortEventURL() != "":
            url = "%s%s" % (Config.getInstance().getShortEventURL(),self.conf.getId())
        else:
            url = urlHandlers.UHConferenceDisplay.getURL( self.conf )
        self.setText("""Hello,
    Please note that the event "%s" will start on %s (%s).
    %s

    You can access the full event here:
    %s

Best Regards

    """%(self.conf.getTitle(),\
                self.conf.getAdjustedStartDate().strftime("%A %d %b %Y at %H:%M"),\
                self.conf.getTimezone(),\
                locationText,\
                url,\
                ))
        self._setMailText()
        return False


class SampleOneShotTask(OneShotTask):
    def run(self):
        self.getLogger().debug('Now i shall sleeeeeeeep!')
        time.sleep(10)
        self.getLogger().debug('%s executed' % self.__class__.__name__)


class SamplePeriodicTask(PeriodicTask):
    def run(self):
        time.sleep(1)
        self.getLogger().debug('%s executed' % self.__class__.__name__)
