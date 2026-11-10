"""The native wizard: one window, a progress rail and one page per step.

Pages are plain ``QWidget`` subclasses with a ``retranslate()`` method. They do
not close over the window; each one gets the services it needs through its
constructor and reports progress with signals.
"""
