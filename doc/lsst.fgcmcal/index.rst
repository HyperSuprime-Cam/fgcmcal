.. py:currentmodule:: lsst.fgcmcal

.. _lsst.fgcmcal:

############
lsst.fgcmcal
############

The ``lsst.fgcmcal`` module runs the Forward Global Calibration Method (FGCM)
to perform global photometric survey calibration for LSST.  Please see [Burke,
Rykoff, et al. 2018](http://adsabs.harvard.edu/abs/2018AJ....155...41B) for the
paper describing the method.  This ``lsst.fgcmcal`` package wraps the
third-party package [fgcm](https://github.com/lsst/fgcm/tree/lsst-dev).

.. _lsst.example.pythononly-using:

Using lsst.fgcmcal
=============================

Please see the
[cookbook](https://github.com/lsst/fgcmcal/tree/master/cookbook/README.md) for
a runthrough on how to use ``lsst.fgcmcal``.

.. _lsst.example.pythononly-contributing:

Contributing
============

``lsst.fgcmcal`` is developed at https://github.com/lsst/fgcmcal.  You can find
Jira issues for this module under the `fgcmcal
<https://jira.lsstcorp.org/browse/DM-16704?jql=text%20~%20%22fgcmcal%22> search
term.

.. _lsst.example.pythononly-command-line-tasks:

Command-line tasks
------------------

.. lsst-cmdlinetasks::
   :root: lsst.fgcmcal

.. _lsst.example.pythononly-tasks:

Configurations
--------------

.. lsst-configs::
   :root: lsst.fgcmcal
   :toctree: configs

.. _lsst.example.pythononly-pyapi:

Python API reference
====================

.. automodapi:: lsst.fgcmcal
   :no-main-docstr:
   :no-inheritance-diagram:
