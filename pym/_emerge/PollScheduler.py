# Copyright 1999-2011 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

import gzip
import errno
import logging
import select
import time

try:
	import threading
except ImportError:
	import dummy_threading as threading

from portage import _encodings
from portage import _unicode_encode
from portage.util import writemsg_level

from _emerge.SlotObject import SlotObject
from _emerge.getloadavg import getloadavg
from _emerge.PollConstants import PollConstants
from _emerge.PollSelectAdapter import PollSelectAdapter

class PollScheduler(object):

	class _sched_iface_class(SlotObject):
		__slots__ = ("output", "register", "schedule", "unregister")

	def __init__(self):
		self._terminated = threading.Event()
		self._terminated_tasks = False
		self._max_jobs = 1
		self._max_load = None
		self._jobs = 0
		self._poll_event_queue = []
		self._poll_event_handlers = {}
		self._poll_event_handler_ids = {}
		# Increment id for each new handler.
		self._event_handler_id = 0
		self._poll_obj = create_poll_instance()
		self._scheduling = False
		self._background = False
		self.sched_iface = self._sched_iface_class(
			output=self._task_output,
			register=self._register,
			schedule=self._schedule_wait,
			unregister=self._unregister)

	def terminate(self):
		"""
		Schedules asynchronous, graceful termination of the scheduler
		at the earliest opportunity.

		This method is thread-safe (and safe for signal handlers).
		"""
		self._terminated.set()

	def _terminate_tasks(self):
		"""
		Send signals to terminate all tasks. This is called once
		from self._schedule() in the event dispatching thread. This
		prevents it from being called while the _schedule_tasks()
		implementation is running, in order to avoid potential
		interference. All tasks should be cleaned up at the earliest
		opportunity, but not necessarily before this method returns.
		"""
		raise NotImplementedError()

	def _schedule_tasks(self):
		"""
		This is called from inside the _schedule() method, which
		guarantees the following:

		1) It will not be called recursively.
		2) _terminate_tasks() will not be called while it is running.
		3) The state of the boolean _terminated_tasks variable will
		   not change while it is running.

		Unless this method is used to perform user interface updates,
		or something like that, the first thing it should do is check
		the state of _terminated_tasks and if that is True then it
		should return False immediately (since there's no need to
		schedule anything after _terminate_tasks() has been called).
		"""
		raise NotImplementedError()

	def _schedule(self):
		"""
		Calls _schedule_tasks() and automatically returns early from
		any recursive calls to this method that the _schedule_tasks()
		call might trigger. This makes _schedule() safe to call from
		inside exit listeners.
		"""
		if self._scheduling:
			return False
		self._scheduling = True
		try:

			if self._terminated.is_set() and \
				not self._terminated_tasks:
				self._terminated_tasks = True
				self._terminate_tasks()

			return self._schedule_tasks()
		finally:
			self._scheduling = False

	def _running_job_count(self):
		return self._jobs

	def _can_add_job(self):
		if self._terminated_tasks:
			return False

		max_jobs = self._max_jobs
		max_load = self._max_load

		if self._max_jobs is not True and \
			self._running_job_count() >= self._max_jobs:
			return False

		if max_load is not None and \
			(max_jobs is True or max_jobs > 1) and \
			self._running_job_count() >= 1:
			try:
				avg1, avg5, avg15 = getloadavg()
			except OSError:
				return False

			if avg1 >= max_load:
				return False

		return True

	def _poll(self, timeout=None):
		"""
		All poll() calls pass through here. The poll events
		are added directly to self._poll_event_queue.
		In order to avoid endless blocking, this raises
		StopIteration if timeout is None and there are
		no file descriptors to poll.
		"""
		if not self._poll_event_handlers:
			self._schedule()
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
		Since the _schedule_wait() loop is called by event
		handlers from _poll_loop(), maintain a central event
		queue for both of them to share events from a single
		poll() call. In order to avoid endless blocking, this
		raises StopIteration if timeout is None and there are
		no file descriptors to poll.
		"""
		if not self._poll_event_queue:
			self._poll(timeout)
			if not self._poll_event_queue:
				raise StopIteration()
		return self._poll_event_queue.pop()

	def _poll_loop(self):

		event_handlers = self._poll_event_handlers
		event_handled = False

		try:
			while event_handlers:
				f, event = self._next_poll_event()
				handler, reg_id = event_handlers[f]
				handler(f, event)
				event_handled = True
		except StopIteration:
			event_handled = True

		if not event_handled:
			raise AssertionError("tight loop")

	def _schedule_yield(self):
		"""
		Schedule for a short period of time chosen by the scheduler based
		on internal state. Synchronous tasks should call this periodically
		in order to allow the scheduler to service pending poll events. The
		scheduler will call poll() exactly once, without blocking, and any
		resulting poll events will be serviced.
		"""
		event_handlers = self._poll_event_handlers
		events_handled = 0

		if not event_handlers:
			return bool(events_handled)

		if not self._poll_event_queue:
			self._poll(0)

		try:
			while event_handlers and self._poll_event_queue:
				f, event = self._next_poll_event()
				handler, reg_id = event_handlers[f]
				handler(f, event)
				events_handled += 1
		except StopIteration:
			events_handled += 1

		return bool(events_handled)

	def _register(self, f, eventmask, handler):
		"""
		@rtype: Integer
		@return: A unique registration id, for use in schedule() or
			unregister() calls.
		"""
		if f in self._poll_event_handlers:
			raise AssertionError("fd %d is already registered" % f)
		self._event_handler_id += 1
		reg_id = self._event_handler_id
		self._poll_event_handler_ids[reg_id] = f
		self._poll_event_handlers[f] = (handler, reg_id)
		self._poll_obj.register(f, eventmask)
		return reg_id

	def _unregister(self, reg_id):
		f = self._poll_event_handler_ids[reg_id]
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
		del self._poll_event_handler_ids[reg_id]

	def _schedule_wait(self, wait_ids=None, timeout=None, condition=None):
		"""
		Schedule until wait_id is not longer registered
		for poll() events.
		@type wait_id: int
		@param wait_id: a task id to wait for
		"""
		event_handlers = self._poll_event_handlers
		handler_ids = self._poll_event_handler_ids
		event_handled = False

		if isinstance(wait_ids, int):
			wait_ids = frozenset([wait_ids])

		start_time = None
		remaining_timeout = timeout
		timed_out = False
		if timeout is not None:
			start_time = time.time()
		try:
			while (wait_ids is None and event_handlers) or \
				(wait_ids is not None and wait_ids.intersection(handler_ids)):
				f, event = self._next_poll_event(timeout=remaining_timeout)
				handler, reg_id = event_handlers[f]
				handler(f, event)
				event_handled = True
				if condition is not None and condition():
					break
				if timeout is not None:
					elapsed_time = time.time() - start_time
					if elapsed_time < 0:
						# The system clock has changed such that start_time
						# is now in the future, so just assume that the
						# timeout has already elapsed.
						timed_out = True
						break
					remaining_timeout = timeout - 1000 * elapsed_time
					if remaining_timeout <= 0:
						timed_out = True
						break
		except StopIteration:
			event_handled = True

		return event_handled

	def _task_output(self, msg, log_path=None, background=None,
		level=0, noiselevel=-1):
		"""
		Output msg to stdout if not self._background. If log_path
		is not None then append msg to the log (appends with
		compression if the filename extension of log_path
		corresponds to a supported compression type).
		"""

		if background is None:
			# If the task does not have a local background value
			# (like for parallel-fetch), then use the global value.
			background = self._background

		msg_shown = False
		if not background:
			writemsg_level(msg, level=level, noiselevel=noiselevel)
			msg_shown = True

		if log_path is not None:
			try:
				f = open(_unicode_encode(log_path,
					encoding=_encodings['fs'], errors='strict'),
					mode='ab')
			except IOError as e:
				if e.errno not in (errno.ENOENT, errno.ESTALE):
					raise
				if not msg_shown:
					writemsg_level(msg, level=level, noiselevel=noiselevel)
			else:

				if log_path.endswith('.gz'):
					# NOTE: The empty filename argument prevents us from
					# triggering a bug in python3 which causes GzipFile
					# to raise AttributeError if fileobj.name is bytes
					# instead of unicode.
					f =  gzip.GzipFile(filename='', mode='ab', fileobj=f)

				f.write(_unicode_encode(msg))
				f.close()

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
