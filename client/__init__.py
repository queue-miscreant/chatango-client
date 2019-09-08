#!/usr/bin/env python3
'''Client package with customizable display and link opening capabilities.'''

from .base import override, Box, OverlayBase, Manager
from .overlay import ListOverlay, VisualListOverlay \
	, ColorOverlay, ColorSliderOverlay, ConfirmOverlay, DisplayOverlay \
	, TabOverlay, InputOverlay, InputMux
from .chat import CommandOverlay, ChatOverlay, Message, add_message_scroller
from .util import Tokenize, tab_file
from .display import Coloring, raw_num, def_color, num_defined_colors, two56
on_done = Manager.on_done
command = CommandOverlay.command
