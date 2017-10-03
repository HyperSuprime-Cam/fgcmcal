# See COPYRIGHT file at the top of the source tree.

from __future__ import division, absolute_import, print_function

import sys
import traceback

import numpy as np

import lsst.utils
import lsst.pex.config as pexConfig
import lsst.pipe.base as pipeBase
import lsst.pex.exceptions as pexExceptions
import lsst.afw.table as afwTable
from lsst.daf.base.dateTime import DateTime
import lsst.afw.geom as afwGeom
import lsst.daf.persistence.butlerExceptions as butlerExceptions
import lsst.daf.persistence


import time

import fgcm


__all__ = ['FgcmBuildStarsConfig','FgcmBuildStarsTask']

class FgcmBuildStarsConfig(pexConfig.Config):
    """Config for FgcmBuildStarsTask"""

    minPerBand = pexConfig.Field(
        doc="Minimum observations per band",
        dtype=int,
        default=2,
        )
    matchRadius = pexConfig.Field(
        doc="Match radius (arcseconds)",
        dtype=float,
        default=1.0,
        )
    isolationRadius = pexConfig.Field(
        doc="Isolation radius (arcseconds)",
        dtype=float,
        default=2.0,
        )
    densityCutNside = pexConfig.Field(
        doc="Density cut healpix nside",
        dtype=int,
        default=128,
        )
    densityCutMaxPerPixel = pexConfig.Field(
        doc="Density cut number of stars per pixel",
        dtype=int,
        default=1000,
        )
    matchNside = pexConfig.Field(
        doc="Healpix Nside for matching",
        dtype=int,
        default=4096,
        )
    zeropointDefault = pexConfig.Field(
        doc="Zeropoint default (arbitrary?)",
        dtype=float,
        default=25.0,
        )
    filterToBand = pexConfig.DictField(
        doc="filterName to band mapping",
        keytype=str,
        itemtype=str,
        default={},
        )
    requiredBands = pexConfig.ListField(
        doc="Bands required for each star",
        dtype=str,
        default=(),
        )
    referenceBand = pexConfig.Field(
        doc="Reference band for primary matches",
        dtype=str,
        default=None
        )
    referenceCCD = pexConfig.Field(
        doc="Reference CCD for scanning visits",
        dtype=int,
        default=13,
        )

    def setDefaults(self):
        pass

class FgcmBuildStarsRunner(pipeBase.ButlerInitializedTaskRunner):
    """Subclass of TaskRunner for fgcmBuildStarsTask

    """

    #TaskClass = FgcmBuildStarsTask

    # only need a single butler instance to run on
    @staticmethod
    def getTargetList(parsedCmd):
        #print("Somebody called FgcmBuildStarsRunner.getTargetList()")
        # we want to combine the butler with any (or no!) dataRefs
        return [(parsedCmd.butler, parsedCmd.id.refList)]

    def precall(self, parsedCmd):
        #print("Somebody called FgcmBuildStarsRunner.precall()")
        return True

    def __call__(self, args):
        #print("Somebody called FgcmBuildStarsRunner()")
        butler, dataRefList = args

        task = self.TaskClass(config=self.config, log=self.log)
        if self.doRaise:
            results = task.run(butler, dataRefList)
        else:
            try:
                results = task.run(butler, dataRefList)
            except Exception as e:
                task.log.fatal("Failed: %s" % e)
                if not isinstance(e, pipeBase.TaskError):
                    traceback.print_exc(file=sys.stderr)

        task.writeMetadata(butler)
        if self.doReturnResults:
            return results

    # turn off any multiprocessing

    def run(self, parsedCmd):
        """ runs the task, but doesn't do multiprocessing"""

        resultList = []

        if self.precall(parsedCmd):
            profileName = parsedCmd.profile if hasattr(parsedCmd, "profile") else None
            log = parsedCmd.log
            targetList = self.getTargetList(parsedCmd)
            # And call the runner on the first (and only) item in the list,
            #  which is a tuple of the butler and any dataRefs
            resultList = self(targetList[0])


        return resultList

class FgcmBuildStarsTask(pipeBase.CmdLineTask):
    """
    Build stars for the FGCM global calibration
    """

    ConfigClass = FgcmBuildStarsConfig
    RunnerClass = FgcmBuildStarsRunner
    _DefaultName = "fgcmBuildStars"

    def __init__(self, butler=None, **kwargs):
        """
        Instantiate an FgcmBuildStarsTask.

        Parameters
        ----------
        butler : lsst.daf.persistence.Butler
          Something about the butler
        """

        pipeBase.CmdLineTask.__init__(self, **kwargs)

    @classmethod
    def _makeArgumentParser(cls):
        """Create an argument parser"""

        parser = pipeBase.ArgumentParser(name=cls._DefaultName)
        parser.add_id_argument("--id", "calexp", help="Data ID, e.g. --id visit=6789 (optional)")

        return parser

    # no saving of the config for now
    #def _getConfigName(self):
    #    return None

    # no saving of metadata for now
    def _getMetadataName(self):
        return None

    @pipeBase.timeMethod
    def run(self, butler, dataRefs):
        """
        Cross-match and make star list for FGCM

        Parameters
        ----------
        butler:  a butler.  try to run all from the rerun?  is that crazy?
        dataRefs: list of lsst.daf.persistence.ButlerDataRef
            List of data references to the exposures to be fit

        Returns
        -------
        pipe.base.Struct
            struct containing:
            * dataRefs: the provided data references consolidated
            (others)
        """

        # make the visit catalog if necessary
        #  question: what's the propper clobber interface?
        #  we also need to know the way of checking the matched config?
        if (butler.datasetExists('fgcmVisitCatalog')):
            visitCat = butler.get('fgcmVisitCatalog')
        else:
            # we need to build visitCat
            visitCat = self._fgcmMakeVisitCatalog(butler, dataRefs)

        # and compile all the stars
        #  this will put this dataset out.
        if (not butler.datasetExists('fgcmStarObservations')):
            self._fgcmMakeAllStarObservations(butler, visitCat)

        if (not butler.datasetExists('fgcmStarIds') or
            not butler.datasetExists('fgcmStarIndices')):
            self._fgcmMatchStars(butler, visitCat)

        # next: need to get a list of source catalogs, etc.
        #  just a few would be fine.  Then I could see the formatting of things.
        # how to get into interactive as well?

        # a-ha!
        # first, need to compile all the visits
        # second, need to compile all the observations

        return None

    def _fgcmMakeVisitCatalog(self, butler, dataRefs):
        """
        """

        startTime = time.time()

        if len(dataRefs) == 0:
            # We did not specify any datarefs, so find all of them
            allVisits = butler.queryMetadata('src',
                                             format=['visit','filter'],
                                             dataId={'CCD':self.config.referenceCCD})

            srcVisits = []
            for dataset in allVisits:
                if (butler.datasetExists('src', dataId={'visit':dataset[0],
                                                        'ccd':self.config.referenceCCD})):
                    srcVisits.append(dataset[0])
        else:
            # get the visits from the datarefs, only for referenceCCD
            srcVisits = [d.dataId['visit'] for d in dataRefs if
                         d.dataId['ccd'] == self.config.referenceCCD]

            # still need to check that these exist!
            ## FIXME

        self.log.info("Found %d visits in %.2f s" %
                      (len(srcVisits), time.time()-startTime))

        schema = afwTable.Schema()
        schema.addField('visit', type=np.int32, doc="Visit number")
        schema.addField('filtername', type=str,size=2, doc="Filter name")
        schema.addField('telra', type=np.float64, doc="Pointing RA (deg)")
        schema.addField('teldec', type=np.float64, doc="Pointing Dec (deg)")
        schema.addField('telha', type=np.float64, doc="Pointing Hour Angle (deg)")
        schema.addField('mjd', type=np.float64, doc="MJD of visit")
        schema.addField('exptime', type=np.float32, doc="Exposure time")
        schema.addField('pmb', type=np.float32, doc="Pressure (millibar)")
        schema.addField('fwhm', type=np.float32, doc="Seeing FWHM?")
        schema.addField('deepflag', type=np.int32, doc="Deep observation")

        visitCat = afwTable.BaseCatalog(schema)
        visitCat.table.preallocate(len(srcVisits))

        startTime = time.time()
        # reading in a small bbox is marginally faster in the scan
        bbox = afwGeom.BoxI(afwGeom.PointI(0, 0), afwGeom.PointI(1, 1))

        # now loop over visits and get the information
        for srcVisit in srcVisits:
            #calexp = butler.get('calexp_sub', dataId={'visit':srcVisit,
            #                                          'ccd':self.config.referenceCCD},
            #                    bbox=bbox)
            raw = butler.get('raw', dataId={'visit':srcVisit,
                                            'ccd':self.config.referenceCCD})

            ##visitInfo = calexp.getInfo().getVisitInfo()
            visitInfo = raw.getInfo().getVisitInfo()

            rec=visitCat.addNew()
            rec['visit'] = srcVisit
            rec['filtername'] = raw.getInfo().getFilter().getName()
            radec = visitInfo.getBoresightRaDec()
            rec['telra'] = radec.getRa().asDegrees()
            rec['teldec'] = radec.getDec().asDegrees()
            rec['telha'] = visitInfo.getBoresightHourAngle().asDegrees()
            rec['mjd'] = visitInfo.getDate().get(system=DateTime.MJD)
            rec['exptime'] = visitInfo.getExposureTime()
            # convert from Pa to millibar
            rec['pmb'] = visitInfo.getWeather().getAirPressure() / 100
            rec['fwhm'] = 0.0
            rec['deepflag'] = 0

        self.log.info("Found all VisitInfo in %.2f s" % (time.time() - startTime))

        # and now persist it
        butler.put(visitCat, 'fgcmVisitCatalog')

        return visitCat

    def _fgcmMakeAllStarObservations(self, butler, visitCat):
        """
        """

        startTime=time.time()

        # create our source schema
        sourceSchema = butler.get('src_schema', immediate=True).schema

        # create a mapper to the preferred output
        sourceMapper = afwTable.SchemaMapper(sourceSchema)

        # map to ra/dec
        sourceMapper.addMapping(sourceSchema.find('coord_ra').key, 'ra')
        sourceMapper.addMapping(sourceSchema.find('coord_dec').key, 'dec')

        # and add the fields we want
        sourceMapper.editOutputSchema().addField(
            "visit", type=np.int32, doc="Visit number")
        sourceMapper.editOutputSchema().addField(
            "ccd", type=np.int32, doc="CCD number")
        sourceMapper.editOutputSchema().addField(
            "mag", type=np.float32, doc="Raw magnitude")
        sourceMapper.editOutputSchema().addField(
            "magerr", type=np.float32, doc="Raw magnitude error")

        # create the stub of the full catalog
        fullCatalog = afwTable.BaseCatalog(sourceMapper.getOutputSchema())

        # we need to know the ccds...
        camera = butler.get('camera')

        started = False

        # loop over visits
        for visit in visitCat:
            self.log.info("Reading sources from visit %d" % (visit['visit']))

            nStarInVisit = 0

            # loop over CCDs
            for detector in camera:
                ccdId = detector.getId()

                # get the dataref -- can't be numpy int
                ref = butler.dataRef('raw', dataId={'visit':int(visit['visit']),
                                                    'ccd':ccdId})
                try:
                    sources = ref.get('src',
                                      flags=afwTable.SOURCE_IO_NO_FOOTPRINTS)
                except butlerExceptions.NoResults:
                    # this ccd does not exist.  That's fine.
                    continue

                if not started:
                    # get the keys for quicker look-up

                    # based pm ApFlux.  Maybe make configurable?
                    fluxKey = sources.getApFluxKey()
                    fluxErrKey = sources.getApFluxErrKey()
                    satCenterKey = sources.schema.find('flag_pixel_saturated_center').key
                    intCenterKey = sources.schema.find('flag_pixel_interpolated_center').key
                    pixEdgeKey = sources.schema.find('flag_pixel_edge').key
                    pixCrCenterKey = sources.schema.find('flag_pixel_cr_center').key
                    pixBadKey = sources.schema.find('flag_pixel_bad').key
                    pixInterpAnyKey = sources.schema.find('flag_pixel_interpolated_any').key
                    centroidFlagKey = sources.schema.find('slot_Centroid_flag').key
                    apFluxFlagKey = sources.schema.find('slot_ApFlux_flag').key
                    deblendNchildKey = sources.schema.find('deblend_nchild').key
                    parentKey = sources.schema.find('parent').key
                    extKey = sources.schema.find('classification_extendedness').key

                    outputSchema = sourceMapper.getOutputSchema()
                    visitKey = outputSchema.find('visit').key
                    ccdKey = outputSchema.find('ccd').key
                    magKey = outputSchema.find('mag').key
                    magErrKey = outputSchema.find('magerr').key

                    started=True


                magErr = (2.5/np.log(10.)) * (sources[fluxKey] /
                                              sources[fluxErrKey])
                magErr = np.nan_to_num(magErr)

                # general flag, child/parent/etc cuts
                # will want to make magErr range configurable.
                #gdFlag = np.logical_and.reduce([~sources['base_PixelFlags_flag_saturatedCenter'],
                #                     ~sources['base_PixelFlags_flag_interpolatedCenter'],
                #                     ~sources['base_PixelFlags_flag_edge'],
                #                     ~sources['base_PixelFlags_flag_crCenter'],
                #                     ~sources['base_PixelFlags_flag_bad'],
                #                     ~sources['base_PixelFlags_flag_interpolated'],
                #                     ~sources['slot_Centroid_flag'],
                #                     ~sources['slot_Centroid_flag_edge'],
                #                     ~sources['slot_ApFlux_flag'],
                #                     ~sources['base_ClassificationExtendedness_flag'],
                #                     sources['deblend_nChild'] == 0,
                #                     sources['parent'] == 0,
                #                     sources['base_ClassificationExtendedness_value'] < 0.5,
                #                     np.isfinite(magErr),
                #                     magErr > 0.001,
                #                     magErr < 0.1])

                magErr = (2.5/np.log(10.)) * (sources[fluxErrKey] /
                                              sources[fluxKey])
                magErr = np.nan_to_num(magErr)

                gdFlag = np.logical_and.reduce([~sources[satCenterKey],
                                                 ~sources[intCenterKey],
                                                 ~sources[pixEdgeKey],
                                                 ~sources[pixCrCenterKey],
                                                 ~sources[pixBadKey],
                                                 ~sources[pixInterpAnyKey],
                                                 ~sources[centroidFlagKey],
                                                 ~sources[apFluxFlagKey],
                                                 sources[deblendNchildKey] == 0,
                                                 sources[parentKey] == 0,
                                                 sources[extKey] < 0.5,
                                                 np.isfinite(magErr),
                                                 magErr > 0.001,
                                                 magErr < 0.1])


                tempCat = afwTable.BaseCatalog(fullCatalog.schema)
                tempCat.table.preallocate(gdFlag.sum())
                tempCat.extend(sources[gdFlag], mapper=sourceMapper)
                tempCat[visitKey][:] = visit['visit']
                tempCat[ccdKey][:] = ccdId
                tempCat[magKey][:] = 25.0 - 2.5*np.log10(sources[fluxKey][gdFlag])
                tempCat[magErrKey][:] = magErr[gdFlag]

                fullCatalog.extend(tempCat)

                nStarInVisit += len(tempCat)

            self.log.info("  Found %d good stars in visit %d" %
                          (nStarInVisit, visit['visit']))

        self.log.info("Found all good star observations in %.2f s" %
                      (time.time() - startTime))

        butler.put(fullCatalog, 'fgcmStarObservations')

        self.log.info("Done with all stars in %.2f s" %
                      (time.time() - startTime))

    def _fgcmMatchStars(self, butler, visitCat):
        """
        """

        obsCat = butler.get('fgcmStarObservations')

        # get filter names into a numpy array...
        visitFilterNames = np.zeros(len(visitCat), dtype='a2')
        for i in xrange(len(visitCat)):
            visitFilterNames[i] = visitCat[i]['filtername']

        # match to put filterNames with observations
        visitIndex = np.searchsorted(visitCat['visit'],
                                     obsCat['visit'])

        obsFilterNames = visitFilterNames[visitIndex]

        # make the fgcm starConfig dict

        starConfig = {'logger': self.log,
                      'filterToBand': self.config.filterToBand,
                      'requiredBands': self.config.requiredBands,
                      'minPerBand': self.config.minPerBand,
                      'matchRadius': self.config.matchRadius,
                      'isolationRadius': self.config.isolationRadius,
                      'matchNSide' : self.config.matchNside,
                      'densNSide': self.config.densityCutNside,
                      'densMaxPerPixel': self.config.densityCutMaxPerPixel,
                      'referenceBand': self.config.referenceBand,
                      'zpDefault': self.config.zeropointDefault}

        # initialize the FgcmMakeStars object
        fgcmMakeStars = fgcm.FgcmMakeStars(starConfig)

        # make the reference stars
        #  note that the ra/dec native Angle format is radians
        fgcmMakeStars.makeReferenceStars(np.rad2deg(obsCat['ra']),
                                         np.rad2deg(obsCat['dec']),
                                         filterNameArray = obsFilterNames,
                                         bandSelected = False)

        # and match all the stars
        fgcmMakeStars.makeMatchedStars(np.rad2deg(obsCat['ra']),
                                       np.rad2deg(obsCat['dec']),
                                       obsFilterNames)

        # now persist

        # afwTable for objects
        objSchema = afwTable.Schema()
        objSchema.addField('fgcm_id', type=np.int32, doc='FGCM Unique ID')
        ## FIXME: should be angle?
        objSchema.addField('ra', type=np.float64, doc='Mean object RA')
        objSchema.addField('dec', type=np.float64, doc='Mean object Dec')
        objSchema.addField('obsarrindex', type=np.int32,
                           doc='Index in obsIndexTable for first observation')
        objSchema.addField('nobs', type=np.int32, doc='Total number of observations')

        # make catalog and records
        fgcmStarIdCat = afwTable.BaseCatalog(objSchema)
        fgcmStarIdCat.table.preallocate(fgcmMakeStars.objIndexCat.size)
        for i in xrange(fgcmMakeStars.objIndexCat.size):
            fgcmStarIdCat.addNew()

        # fill the catalog
        fgcmStarIdCat['fgcm_id'][:] = fgcmMakeStars.objIndexCat['FGCM_ID']
        fgcmStarIdCat['ra'][:] = fgcmMakeStars.objIndexCat['RA']
        fgcmStarIdCat['dec'][:] = fgcmMakeStars.objIndexCat['DEC']
        fgcmStarIdCat['obsarrindex'][:] = fgcmMakeStars.objIndexCat['OBSARRINDEX']
        fgcmStarIdCat['nobs'][:] = fgcmMakeStars.objIndexCat['NOBS']

        butler.put(fgcmStarIdCat, 'fgcmStarIds')

        # afwTable for observation indices
        obsSchema = afwTable.Schema()
        obsSchema.addField('obsindex', type=np.int32, doc='Index in observation table')

        fgcmStarIndicesCat = afwTable.BaseCatalog(obsSchema)
        fgcmStarIndicesCat.table.preallocate(fgcmMakeStars.obsIndexCat.size)
        for i in xrange(fgcmMakeStars.obsIndexCat.size):
            fgcmStarIndicesCat.addNew()

        fgcmStarIndicesCat['obsindex'][:] = fgcmMakeStars.obsIndexCat['OBSINDEX']

        butler.put(fgcmStarIndicesCat, 'fgcmStarIndices')

        # and we're done with the stars
