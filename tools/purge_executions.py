#!/usr/bin/env python
# Licensed to the StackStorm, Inc ('StackStorm') under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
A utility script that purges st2 executions older than certain
timestamp.

*** RISK RISK RISK. You will lose data. Run at your own risk. ***
"""

from datetime import datetime
import pytz
import sys

from oslo_config import cfg

from st2common import config
from st2common import log as logging
from st2common.constants import action as action_constants
from st2common.script_setup import setup as common_setup
from st2common.script_setup import teardown as common_teardown
from st2common.persistence.liveaction import LiveAction
from st2common.persistence.execution import ActionExecution
from st2common.util import isotime

LOG = logging.getLogger(__name__)
DELETED_COUNT = 0

IN_PROGRESS_STATES = [action_constants.LIVEACTION_STATUS_RUNNING,
                      action_constants.LIVEACTION_STATUS_SCHEDULED,
                      action_constants.LIVEACTION_STATUS_REQUESTED,
                      action_constants.LIVEACTION_STATUS_CANCELING,
                      action_constants.LIVEACTION_STATUS_DELAYED]


def _do_register_cli_opts(opts, ignore_errors=False):
    for opt in opts:
        try:
            cfg.CONF.register_cli_opt(opt)
        except:
            if not ignore_errors:
                raise


def _register_cli_opts():
    cli_opts = [
        cfg.StrOpt('timestamp', default=None,
                   help='Will delete execution and liveaction models older than ' +
                   'this UTC timestamp. ' +
                   'Example value: 2015-03-13T19:01:27.255542Z.'),
        cfg.StrOpt('action-ref', default='',
                   help='action-ref to delete executions for.'),
    ]
    _do_register_cli_opts(cli_opts)


def _purge_models(execution_db):
    liveaction_id = execution_db.liveaction.get('id', None)

    if not liveaction_id:
        LOG.error('Invalid LiveAction id. Skipping delete: %s', execution_db)

    liveaction_db = None
    try:
        liveaction_db = LiveAction.get_by_id(liveaction_id)
    except:
        LOG.exception('LiveAction with id: %s not found. Skipping delete.', liveaction_id)
    else:
        global DELETED_COUNT
        DELETED_COUNT += 1

    try:
        ActionExecution.delete(execution_db)
    except:
        LOG.exception('Exception deleting Execution model: %s',
                      execution_db)
    else:
        if liveaction_db:
            try:
                LiveAction.delete(liveaction_db)
            except:
                LOG.exception('Zombie LiveAction left in db: %s.', liveaction_db)


def _should_delete(execution_db, action_ref, timestamp):
    if execution_db.status in IN_PROGRESS_STATES:
        return False

    if action_ref != '':
        return (execution_db.liveaction['action'] == action_ref and
                execution_db.start_timestamp < timestamp)
    else:
        return execution_db.start_timestamp < timestamp


def purge_executions(timestamp=None, action_ref=None):
    if not timestamp:
        LOG.error('Specify a valid timestamp to purge.')
        return

    if not action_ref:
        action_ref = ''

    LOG.info('Purging executions older than timestamp: %s' %
             timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

    # XXX: Think about paginating this call.
    filters = {'end_timestamp__lt': isotime.parse(timestamp)}
    executions = ActionExecution.query(**filters)
    executions_to_delete = [execution for execution in executions
                            if _should_delete(execution, action_ref, timestamp)]
    LOG.info('#### Total number of executions to delete: %d' % len(executions_to_delete))

    # Purge execution and liveaction models now
    for execution_db in executions_to_delete:
        _purge_models(execution_db)

    # Print stats
    LOG.info('#### Total execution models deleted: %d' % DELETED_COUNT)


def main():
    _register_cli_opts()
    common_setup(config=config, setup_db=True, register_mq_exchanges=True)

    # Get config values
    timestamp = cfg.CONF.timestamp
    action_ref = cfg.CONF.action_ref

    if not timestamp:
        LOG.error('Please supply a timestamp for purging models. Aborting.')
        return 1
    else:
        timestamp = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
        timestamp = timestamp.replace(tzinfo=pytz.UTC)

    # Purge models.
    purge_executions(timestamp=timestamp, action_ref=action_ref)

    common_teardown()

if __name__ == '__main__':
    sys.exit(main())
