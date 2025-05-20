#!/usr/bin/env python3

"""
Author: Donatas Olsevicius

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see
<https://www.gnu.org/licenses/>.
"""

import traceback
# noinspection PyUnresolvedReferences
from interpreter import *
from .atc import Rcatc
from .emc import Constants
from qtvcp import logger

throw_exceptions = 1

log = logger.getLogger(__name__)
log.setLevel(logger.WARNING)

__all__ = ['rcatc_tool_change']


# REMAP=M6 modalgroup=6 prolog=change_prolog python=rcatc_tool_change epilog=change_epilog
def rcatc_tool_change(self):
    if self.task == 0:  # ignore the preview interpreter
        yield Constants.OK
        return

    try:
        atc = Rcatc(self)
        atc.setup_signals()

        yield from atc.change_tool()
    except Exception as e:
        traceback.print_exc()
        self.runtime.set_errormsg(str(e))
        log.debug(e)
        yield Constants.ERROR
        return

    yield Constants.OK
