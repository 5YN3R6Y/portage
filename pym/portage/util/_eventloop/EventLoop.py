# Copyright 1999-2012 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

import logging
import select
import time

from portage.util import writemsg_level

from _emerge.SlotObject import SlotObject
from _emerge.PollConstants import PollConstants
from _emerge.PollSelectAdapter import PollSelectAdapter

class EventLoop(object):

	class _idle_callback_class(SlotObject):
		__slots__ = ("args", "callback", "source_id")

	class _io_handler_class(SlotObject):
		__slots__ = ("args", "callback", "fd", "source_id")

	class _timeout_handler_class(SlotObject):
		__slots__ = ("args", "function", "interval", "source_id",
			"timestamp")

	def __init__(self):
		self._poll_event_queue = []
		self._poll_event_handlers = {}
		self._poll_event_handler_ids = {}
		# Increment id for each new handler.
		self._event_handler_id = 0
		self._idle_callbacks = {}
		self._timeout_handlers = {}
		self._timeout_interval = None
		self._poll_obj = create_poll_instance()
		self._polling = False

	def _poll(self, timeout=None):
		if self._polling:
			return
		self._polling = True
		try:
			if self._timeout_interval is None:
				self._run_timeouts()
				self._do_poll(timeout=timeout)

			elif timeout is None:
				while True:
					self._run_timeouts()
					previous_count = len(self._poll_event_queue)
					self._do_poll(timeout=self._timeout_interval)
					if previous_count != len(self._poll_event_queue):
						break

			elif timeout <= self._timeout_interval:
				self._run_timeouts()
				self._do_poll(timeout=timeout)

			else:
				remaining_timeout = timeout
				start_time = time.time()
				while True:
					self._run_timeouts()
					# _timeout_interval can change each time
					# _run_timeouts is called
					min_timeout = remaining_timeout
					if self._timeout_interval is not None and \
						self._timeout_interval < min_timeout:
						min_timeout = self._timeout_interval

					previous_count = len(self._poll_event_queue)
					self._do_poll(timeout=min_timeout)
					if previous_count != len(self._poll_event_queue):
						break
					elapsed_time = time.time() - start_time
					if elapsed_time < 0:
						# The system clock has changed such that start_time
						# is now in the future, so just assume that the
						# timeout has already elapsed.
						break
					remaining_timeout = timeout - 1000 * elapsed_time
					if remaining_timeout <= 0:
						break
		finally:
			self._polling = False

	def _do_poll(self, timeout=None):
		"""
		All poll() calls pass through here. The poll events
		are added directly to self._poll_event_queue.
		In order to avoid endless blocking, this raises
		StopIteration if timeout is None and there are
		no file descriptors to poll.
		"""

		if timeout is None and \
			not self._poll_event_handlers:
			raise StopIteration(
				"timeout is None and there are no poll() event handlers")

		# The following error is known to occur with Linux kernel versions
		# less than 2.6.24:
		#
		#   select.error: (4, 'Interrupted system call')
		#
		# This error has been observed after a SIGSTOP, followed by SIGCONT.
		# Treat it similar to EAGAIN if timeout is None, otherwise just return
		# without any events.
		while True:
			try:
				self._poll_event_queue.extend(self._poll_obj.poll(timeout))
				break
			except select.error as e:
				writemsg_level("\n!!! select error: %s\n" % (e,),
					level=logging.ERROR, noiselevel=-1)
				del e
				if timeout is not None:
					break

	def _next_poll_event(self, timeout=None):
		"""
		Since iteration() can be called recursively, maintain
		a central event queue to share events from a single
		poll() call. In order to avoid endless blocking, this
		raises StopIteration if timeout is None and there are
		no file descriptors to poll.
		"""
		if not self._poll_event_queue:
			self._poll(timeout)
			if not self._poll_event_queue:
				raise StopIteration()
		return self._poll_event_queue.pop()

	def iteration(self, *args):
		"""
		Like glib.MainContext.iteration(), runs a single iteration.
		@type may_block: bool
		@param may_block: if True the call may block waiting for an event
			(default is True).
		@rtype: bool
		@return: True if events were dispatched.
		"""

		may_block = True

		if args:
			if len(args) > 1:
				raise TypeError(
					"expected at most 1 argument (%s given)" % len(args))
			may_block = args[0]

		event_handlers = self._poll_event_handlers
		events_handled = 0

		if not event_handlers:
			return bool(events_handled)

		if not self._poll_event_queue:
			if may_block:
				timeout = None
			else:
				timeout = 0
			self._poll(timeout=timeout)

		try:
			while event_handlers and self._poll_event_queue:
				f, event = self._next_poll_event()
				x = event_handlers[f]
				if not x.callback(f, event, *x.args):
					self.source_remove(x.source_id)
				events_handled += 1
		except StopIteration:
			events_handled += 1

		return bool(events_handled)

	def idle_add(self, callback, *args):
		"""
		Like glib.idle_add(), if callback returns False it is
		automatically removed from the list of event sources and will
		not be called again.

		@type callback: callable
		@param callback: a function to call
		@rtype: int
		@return: an integer ID
		"""
		self._event_handler_id += 1
		source_id = self._event_handler_id
		self._idle_callbacks[source_id] = self._idle_callback_class(
			args=args, callback=callback, source_id=source_id)
		return source_id

	def _run_idle_callbacks(self):
		if not self._idle_callbacks:
			return
		# Iterate of our local list, since self._idle_callbacks can be
		# modified during the exection of these callbacks.
		for x in list(self._idle_callbacks.values()):
			if x.source_id not in self._idle_callbacks:
				# it got cancelled while executing another callback
				continue
			if not x.callback(*x.args):
				self.source_remove(x.source_id)

	def timeout_add(self, interval, function, *args):
		"""
		Like glib.timeout_add(), interval argument is the number of
		milliseconds between calls to your function, and your function
		should return False to stop being called, or True to continue
		being called. Any additional positional arguments given here
		are passed to your function when it's called.

		NOTE: Timeouts registered by this function currently do not
		keep the main loop running when there are no remaining callbacks
		registered for IO events. This is not an issue if the purpose of
		the timeout is to place an upper limit on the time allowed for
		a particular IO event to occur, since the handler associated with
		the IO event will serve to keep the main loop running.
		"""
		self._event_handler_id += 1
		source_id = self._event_handler_id
		self._timeout_handlers[source_id] = \
			self._timeout_handler_class(
				interval=interval, function=function, args=args,
				source_id=source_id, timestamp=time.time())
		if self._timeout_interval is None or self._timeout_interval < interval:
			self._timeout_interval = interval
		return source_id

	def _run_timeouts(self):

		self._run_idle_callbacks()

		if not self._timeout_handlers:
			return False

		ready_timeouts = []
		current_time = time.time()
		for x in self._timeout_handlers.values():
			elapsed_seconds = current_time - x.timestamp
			# elapsed_seconds < 0 means the system clock has been adjusted
			if elapsed_seconds < 0 or \
				(x.interval - 1000 * elapsed_seconds) <= 0:
				ready_timeouts.append(x)

		# Iterate of our local list, since self._timeout_handlers can be
		# modified during the exection of these callbacks.
		for x in ready_timeouts:
			if x.source_id not in self._timeout_handlers:
				# it got cancelled while executing another timeout
				continue
			x.timestamp = time.time()
			if not x.function(*x.args):
				self.source_remove(x.source_id)

		return bool(ready_timeouts)

	def io_add_watch(self, f, condition, callback, *args):
		"""
		Like glib.io_add_watch(), your function should return False to
		stop being called, or True to continue being called. Any
		additional positional arguments given here are passed to your
		function when it's called.

		@type f: int or object with fileno() method
		@param f: a file descriptor to monitor
		@type condition: int
		@param condition: a condition mask
		@type callback: callable
		@param callback: a function to call
		@rtype: int
		@return: an integer ID of the event source
		"""
		if f in self._poll_event_handlers:
			raise AssertionError("fd %d is already registered" % f)
		self._event_handler_id += 1
		source_id = self._event_handler_id
		self._poll_event_handler_ids[source_id] = f
		self._poll_event_handlers[f] = self._io_handler_class(
			args=args, callback=callback, f=f, source_id=source_id)
		self._poll_obj.register(f, condition)
		return source_id

	def source_remove(self, reg_id):
		"""
		Like glib.source_remove(), this returns True if the given reg_id
		is found and removed, and False if the reg_id is invalid or has
		already been removed.
		"""
		idle_callback = self._idle_callbacks.pop(reg_id, None)
		if idle_callback is not None:
			return True
		timeout_handler = self._timeout_handlers.pop(reg_id, None)
		if timeout_handler is not None:
			if timeout_handler.interval == self._timeout_interval:
				if self._timeout_handlers:
					self._timeout_interval = \
						min(x.interval for x in self._timeout_handlers.values())
				else:
					self._timeout_interval = None
			return True
		f = self._poll_event_handler_ids.pop(reg_id, None)
		if f is None:
			return False
		self._poll_obj.unregister(f)
		if self._poll_event_queue:
			# Discard any unhandled events that belong to this file,
			# in order to prevent these events from being erroneously
			# delivered to a future handler that is using a reallocated
			# file descriptor of the same numeric value (causing
			# extremely confusing bugs).
			remaining_events = []
			discarded_events = False
			for event in self._poll_event_queue:
				if event[0] == f:
					discarded_events = True
				else:
					remaining_events.append(event)

			if discarded_events:
				self._poll_event_queue[:] = remaining_events

		del self._poll_event_handlers[f]
		return True

_can_poll_device = None

def can_poll_device():
	"""
	Test if it's possible to use poll() on a device such as a pty. This
	is known to fail on Darwin.
	@rtype: bool
	@returns: True if poll() on a device succeeds, False otherwise.
	"""

	global _can_poll_device
	if _can_poll_device is not None:
		return _can_poll_device

	if not hasattr(select, "poll"):
		_can_poll_device = False
		return _can_poll_device

	try:
		dev_null = open('/dev/null', 'rb')
	except IOError:
		_can_poll_device = False
		return _can_poll_device

	p = select.poll()
	p.register(dev_null.fileno(), PollConstants.POLLIN)

	invalid_request = False
	for f, event in p.poll():
		if event & PollConstants.POLLNVAL:
			invalid_request = True
			break
	dev_null.close()

	_can_poll_device = not invalid_request
	return _can_poll_device

def create_poll_instance():
	"""
	Create an instance of select.poll, or an instance of
	PollSelectAdapter there is no poll() implementation or
	it is broken somehow.
	"""
	if can_poll_device():
		return select.poll()
	return PollSelectAdapter()
