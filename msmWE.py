from __future__ import division, print_function

__metaclass__ = type
import numpy as np
import os
import sys
import subprocess
import h5py
from scipy.sparse import coo_matrix

# sys.path.append(os.environ["WEST_ROOT"]+'/src')
# sys.path.append(os.environ["WEST_ROOT"]+'/lib/west_tools')
# sys.path.append(os.environ["WEST_ROOT"]+'/src/west')
# sys.path.append(os.environ["WEST_ROOT"]+'/lib/wwmgr')
# sys.path.append(os.environ["WEST_ROOT"]+'/src/west')
# import west
# from west import WESTSystem
# from westpa.binning import RectilinearBinMapper
# import warnings
import matplotlib

# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import mdtraj as md
import pyemma.coordinates as coor
import pyemma.coordinates.clustering as clustering
import pyemma


class modelWE:
    """
    Implementation of haMSM model building, particularly for steady-state estimation (but there are lots of extras),
    from WE sampling with basis (source) and target (sink) states with recycling.

    Set up for typical west.h5 file structure, with coordinates to be stored in west.h5 /iterations/auxdata/coord and
    basis and target definitions from progress coordinates. Check out run_msmWE.slurm and run_msmWE_flux.py in scripts
    folder for an implementation example. See Copperman and Zuckerman, Accelerated estimation of long-timescale kinetics
    by combining weighted ensemble simulation with Markov model microstates using non-Markovian theory, arXiv (2020).
    """

    def initialize(self, fileSpecifier, refPDBfile, initPDBfile, modelName):
        self.modelName = modelName
        pCommand = "ls " + fileSpecifier
        p = subprocess.Popen(pCommand, stdout=subprocess.PIPE, shell=True)
        (output, err) = p.communicate()
        output = output.decode()
        fileList = output.split("\n")
        fileList = fileList[0:-1]
        self.fileList = fileList
        nF = len(fileList)
        self.nF = nF
        self.pcoord_ndim = 1
        self.pcoord_len = 2
        tau = 10.0e-12
        self.tau = tau
        self.set_topology(refPDBfile)
        self.set_basis(initPDBfile)
        self.WEtargetp1 = 1.25  # target def on WE p1
        self.WEbasisp1_min = 12.0  # WE bin where basis structure is mapped
        self.WEbasisp1_max = 12.5
        self.dimReduceMethod = "pca"
        self.vamp_lag = 10
        self.vamp_dim = 10
        self.nB = 48  # number of bins for optimized WE a la Aristoff
        self.nW = 40  # number of walkers for optimized WE a la Aristoff
        self.min_walkers = 1  # minimum number of walkers per bin
        self.binMethod = "adaptive"  # adaptive for dynamic k-means bin edges, uniform for equal spacing on kh
        self.allocationMethod = (
            "adaptive"  # adaptive for dynamic allocation, uniform for equal allocation
        )
        try:
            self.get_iter_data(1)
            self.get_iter_coordinates0()
            self.coordsExist = True
        except:
            sys.stdout.write("problem getting coordinates \n")
            self.coordsExist = False

    def is_WE_basis(self, pcoords):
        isBasis = np.logical_and(
            pcoords[:, 0] > self.WEbasisp1_min, pcoords[:, 0] < self.WEbasisp1_max
        )
        return isBasis

    def is_WE_target(self, pcoords):
        isTarget = pcoords[:, 0] < self.WEtargetp1
        return isTarget

    def get_iter_data(self, n_iter):
        self.n_iter = n_iter
        westList = np.array([])
        segindList = np.array([])
        weightList = np.array([])
        pcoord0List = np.empty((0, self.pcoord_ndim))
        pcoord1List = np.empty((0, self.pcoord_ndim))
        nSeg = 0
        for iF in range(self.nF):
            fileName = self.fileList[iF]
            try:
                dataIn = h5py.File(fileName, "r")
                dsetName = "/iterations/iter_%08d/seg_index" % int(n_iter)
                e = dsetName in dataIn
                if e:
                    dset = dataIn[dsetName]
                    newSet = dset[:]
                    nS = np.shape(newSet)
                    nS = nS[0]
                    dsetNameP = "/iterations/iter_%08d/pcoord" % int(n_iter)
                    dsetP = dataIn[dsetNameP]
                    pcoord = dsetP[:]
                    for iS in range(nS):
                        # if np.sum(pcoord[iS,self.pcoord_len-1,:])==0.0: #intentionally using this to write in dummy pcoords, this is a good thing to have for post-analysis though!
                        #    raise ValueError('Sum pcoord is 0, probably middle of WE iteration, not using iteration') f
                        westList = np.append(westList, iF)
                        segindList = np.append(segindList, iS)
                        weightList = np.append(weightList, newSet[iS][0])
                        pcoord0List = np.append(
                            pcoord0List, np.expand_dims(pcoord[iS, 0, :], 0), axis=0
                        )
                        pcoord1List = np.append(
                            pcoord1List,
                            np.expand_dims(pcoord[iS, self.pcoord_len - 1, :], 0),
                            axis=0,
                        )
                        nSeg = nSeg + 1
                dataIn.close()
            except:
                sys.stdout.write("error in " + fileName + str(sys.exc_info()[0]) + "\n")
        self.westList = westList.astype(int)
        self.segindList = segindList.astype(int)
        self.weightList = weightList
        self.nSeg = nSeg
        self.pcoord0List = pcoord0List
        self.pcoord1List = pcoord1List

    def get_iterations(self):
        numFiles = np.array([])
        numSegments = np.array([])
        iterationList = np.array([])
        nSeg = 1
        n_iter = 1
        while nSeg > 0:
            nSeg = 0
            for iF in range(self.nF):
                fileName = self.fileList[iF]
                try:
                    dataIn = h5py.File(fileName, "r")
                    dsetName = "/iterations/iter_%08d/seg_index" % int(n_iter)
                    e = dsetName in dataIn
                    if e:
                        dset = dataIn[dsetName]
                        newSet = dset[:]
                        nS = np.shape(newSet)
                        nSeg = nS[0] + nSeg
                    dataIn.close()
                except:
                    sys.stdout.write(
                        "no segments in " + fileName + str(sys.exc_info()[0]) + "\n"
                    )
            if nSeg > 0:
                numSegments = np.append(numSegments, nSeg)
                sys.stdout.write(
                    "Iteration " + str(n_iter) + " has " + str(nSeg) + " segments...\n"
                )
            n_iter = n_iter + 1
        self.numSegments = numSegments
        self.maxIter = numSegments.size

    def get_iterations_iters(self, first_iter, last_iter):
        numFiles = np.array([])
        numSegments = np.array([])
        iterationList = np.array([])
        nSeg = 1
        for n_iter in range(first_iter, last_iter + 1):
            nSeg = 0
            for iF in range(self.nF):
                fileName = self.fileList[iF]
                try:
                    dataIn = h5py.File(fileName, "r")
                    dsetName = "/iterations/iter_%08d/seg_index" % int(n_iter)
                    e = dsetName in dataIn
                    if e:
                        dset = dataIn[dsetName]
                        newSet = dset[:]
                        nS = np.shape(newSet)
                        nSeg = nS[0] + nSeg
                    dataIn.close()
                except:
                    sys.stdout.write(
                        "no segments in " + fileName + str(sys.exc_info()[0]) + "\n"
                    )
            if nSeg > 0:
                numSegments = np.append(numSegments, nSeg)
                sys.stdout.write(
                    "Iteration " + str(n_iter) + " has " + str(nSeg) + " segments...\n"
                )
        self.numSegments = numSegments
        self.maxIter = last_iter

    def set_topology(self, PDBfile):
        if PDBfile[-3:] == "dat":
            self.reference_coord = np.loadtxt(PDBfile)
            self.nAtoms = 1
        elif PDBfile[-3:] == "pdb":
            struct = md.load(PDBfile)
            self.reference_structure = struct
            self.reference_coord = np.squeeze(struct._xyz)
            self.nAtoms = struct.topology.n_atoms

    def set_basis(self, PDBfile):
        if PDBfile[-3:] == "dat":
            self.basis_coords = np.loadtxt(PDBfile)
        elif PDBfile[-3:] == "pdb":
            struct = md.load(PDBfile)
            self.basis_structure = struct
            self.basis_coords = np.squeeze(struct._xyz)

    def get_transition_data(
        self, n_lag
    ):  # get segment history data at lag time n_lag from current iter
        if n_lag > self.n_iter:
            sys.stdout.write(
                "too much lag for iter... n_lag reduced to: " + str(self.n_iter) + "\n"
            )
            n_lag = self.n_iter
        if n_lag >= self.n_hist:
            sys.stdout.write("too much lag for stored history... recalculating...\n")
            self.get_seg_histories(n_lag)
        self.n_lag = n_lag
        segindList_lagged = self.seg_histories[:, n_lag]
        warpList = self.seg_histories[:, 0:n_lag]  # check for warps
        warpList = np.sum(warpList < 0, 1)
        weightList_lagged = self.weight_histories[:, n_lag]
        weightList = self.weightList
        coordPairList = np.zeros((self.nSeg, self.nAtoms, 3, 2))
        prewarpedStructures = np.zeros((self.nSeg, self.nAtoms, 3))
        nWarped = 0
        for iS in range(self.nSeg):
            try:
                if iS == 0:
                    westFile = self.fileList[self.westList[iS]]
                    dataIn = h5py.File(westFile, "r")
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                    dset = dataIn[dsetName]
                    coords_current = dset[:]
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(
                        self.n_iter - n_lag
                    )
                    dset = dataIn[dsetName]
                    coords_lagged = dset[:]
                elif self.westList[iS] != self.westList[iS - 1]:
                    dataIn.close()
                    westFile = self.fileList[self.westList[iS]]
                    dataIn = h5py.File(westFile, "r")
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                    dset = dataIn[dsetName]
                    coords_current = dset[:]
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(
                        self.n_iter - n_lag
                    )
                    dset = dataIn[dsetName]
                    coords_lagged = dset[:]
                coordPairList[iS, :, :, 1] = coords_current[
                    self.segindList[iS], 1, :, :
                ]
                if warpList[iS] == 0:
                    coordPairList[iS, :, :, 0] = coords_lagged[
                        segindList_lagged[iS], 0, :, :
                    ]
                elif warpList[iS] > 0:
                    prewarpedStructures[nWarped, :, :] = coords_lagged[
                        segindList_lagged[iS], 0, :, :
                    ]
                    coordPairList[iS, :, :, 0] = self.basis_coords
                    nWarped = nWarped + 1
            except:
                weightList_lagged[iS] = 0.0
                weightList[
                    iS
                ] = 0.0  # set transitions without structures to zero weight
        indWarped = np.squeeze(np.where(warpList > 0))
        indWarpedArray = np.empty(nWarped)
        indWarpedArray[0:nWarped] = indWarped
        indWarped = indWarpedArray.astype(int)
        transitionWeights = weightList.copy()
        departureWeights = weightList_lagged.copy()
        for iW in range(nWarped):
            coordPair = np.zeros((1, self.nAtoms, 3, 2))
            coordPair[0, :, :, 0] = prewarpedStructures[iW, :, :]
            coordPair[0, :, :, 1] = self.reference_coord
            coordPairList = np.append(coordPairList, coordPair, axis=0)
            iterWarped = np.squeeze(np.where(self.seg_histories[indWarped[iW], :] < 0))
            try:
                nW = np.shape(iterWarped)
                iterWarped = iterWarped[0]
                sys.stdout.write(
                    "    segment "
                    + str(indWarped[iW])
                    + " warped "
                    + str(nW)
                    + " times\n"
                )
            except:
                sys.stdout.write(
                    "    segment " + str(indWarped[iW]) + " warped 1 time\n"
                )
            transitionWeights = np.append(
                transitionWeights, self.weight_histories[indWarped[iW], iterWarped]
            )
            departureWeights = np.append(
                departureWeights, self.weight_histories[indWarped[iW], n_lag]
            )
        self.coordPairList = coordPairList
        self.transitionWeights = transitionWeights
        self.departureWeights = departureWeights

    def get_transition_data_lag0(
        self,
    ):  # get segment history data at lag time n_lag from current iter
        weightList = self.weightList
        coordPairList = np.zeros((self.nSeg, self.nAtoms, 3, 2))
        for iS in range(self.nSeg):
            try:
                if iS == 0:
                    westFile = self.fileList[self.westList[iS]]
                    dataIn = h5py.File(westFile, "r")
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                    dset = dataIn[dsetName]
                    coords = dset[:]
                elif self.westList[iS] != self.westList[iS - 1]:
                    dataIn.close()
                    westFile = self.fileList[self.westList[iS]]
                    dataIn = h5py.File(westFile, "r")
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                    dset = dataIn[dsetName]
                    coords = dset[:]
                coordPairList[iS, :, :, 1] = coords[
                    self.segindList[iS], self.pcoord_len - 1, :, :
                ]
                coordPairList[iS, :, :, 0] = coords[self.segindList[iS], 0, :, :]
            except:
                self.errorWeight = self.errorWeight + weightList[iS]
                weightList[
                    iS
                ] = 0.0  # set transitions without structures to zero weight
                self.errorCount = self.errorCount + 1
        transitionWeights = weightList.copy()
        departureWeights = weightList.copy()
        self.coordPairList = coordPairList
        self.transitionWeights = transitionWeights
        self.departureWeights = departureWeights

    def get_warps_from_parent(
        self, first_iter, last_iter
    ):  # get all warps and weights over set of iterations
        warpedWeights = []
        for iS in range(first_iter + 1, last_iter + 1):
            self.get_iter_data(iS + 1)
            self.get_seg_histories(2)
            parentList = self.seg_histories[:, 1]
            warpList = np.where(parentList < 0)
            warpedWeights.append(self.weightList[warpList])
        return warpedWeights

    def get_warps_from_pcoord(
        self, first_iter, last_iter
    ):  # get all warps and weights over set of iterations
        warpedWeights = []
        for iS in range(first_iter, last_iter + 1):
            self.get_iter_data(iS)
            pcoord = self.pcoord1List[:, 0]
            warpList = np.where(pcoord < self.WEtargetp1)
            warpedWeights.append(self.weightList[warpList])
            meanJ = (
                np.mean(self.weightList[warpList]) / self.tau / np.sum(self.weightList)
            )
            sys.stdout.write("Jdirect: " + str(meanJ) + " iter: " + str(iS) + "\n")
        return warpedWeights

    def get_direct_target_flux(self, first_iter, last_iter, window):
        nIterations = last_iter - first_iter
        Jdirect = np.zeros(nIterations - 1)
        f = h5py.File(self.modelName + ".h5", "a")
        dsetName = (
            "/s"
            + str(first_iter)
            + "_e"
            + str(last_iter)
            + "_w"
            + str(window)
            + "/Jdirect"
        )
        e = dsetName in f
        if not e:
            warpedWeights = self.get_warps_from_pcoord(first_iter, last_iter)
            self.warpedWeights = warpedWeights
            JdirectTimes = np.zeros(nIterations - 1)
            for iS in range(nIterations - 1):
                end = iS + 1
                start = iS - window
                if start < 0:
                    start = 0
                nI = end - start
                warpedWeightsI = np.array([])
                for i in range(start, end):
                    warpedWeightsI = np.append(warpedWeightsI, warpedWeights[i])
                nWarped = warpedWeightsI.size
                particles = (nWarped * warpedWeightsI) / nI
                Jdirect[iS] = np.mean(particles)
                JdirectTimes[iS] = (first_iter + iS) * self.tau
            Jdirect = Jdirect / self.tau
            dsetP = f.create_dataset(dsetName, np.shape(Jdirect))
            dsetP[:] = Jdirect
            dsetName = (
                "/s"
                + str(first_iter)
                + "_e"
                + str(last_iter)
                + "_w"
                + str(window)
                + "/JdirectTimes"
            )
            dsetP = f.create_dataset(dsetName, np.shape(JdirectTimes))
            dsetP[:] = JdirectTimes
        elif e:
            dsetP = f[dsetName]
            Jdirect = dsetP[:]
            dsetName = (
                "/s"
                + str(first_iter)
                + "_e"
                + str(last_iter)
                + "_w"
                + str(window)
                + "/JdirectTimes"
            )
            dsetP = f[dsetName]
            JdirectTimes = dsetP[:]
        f.close()
        self.Jdirect = Jdirect / self.nF  # correct for number of trees
        self.JdirectTimes = JdirectTimes

    def get_seg_histories(self, n_hist):
        if n_hist > self.n_iter:
            sys.stdout.write(
                "we have too much history... n_hist reduced to: "
                + str(self.n_iter)
                + "\n"
            )
            n_hist = self.n_iter
        self.n_hist = n_hist
        seg_histories = np.zeros((self.nSeg, self.n_hist + 1))
        weight_histories = np.zeros((self.nSeg, self.n_hist))
        for iS in range(self.nSeg):
            if iS % 100 == 0:
                sys.stdout.write(
                    "        getting history for iteration "
                    + str(self.n_iter)
                    + " segment "
                    + str(iS)
                    + "...\n"
                )
            if iS == 0:
                westFile = self.fileList[self.westList[iS]]
                dataIn = h5py.File(westFile, "r")
            elif self.westList[iS] != self.westList[iS - 1]:
                dataIn.close()
                westFile = self.fileList[self.westList[iS]]
                dataIn = h5py.File(westFile, "r")
            seg_histories[iS, 0] = self.segindList[iS]
            warped = 0
            for iH in range(1, self.n_hist + 1):
                indCurrentSeg = seg_histories[iS, iH - 1]
                if indCurrentSeg < 0 and warped == 0:
                    sys.stdout.write(
                        "Segment "
                        + str(iS)
                        + " warped last iter: History must end NOW!\n"
                    )
                    warped = 1
                elif indCurrentSeg >= 0 and warped == 0:
                    dsetName = "/iterations/iter_%08d/seg_index" % int(
                        self.n_iter - iH + 1
                    )
                    dset = dataIn[dsetName]
                    seg_histories[iS, iH] = dset[indCurrentSeg][1]
                    weight_histories[iS, iH - 1] = dset[indCurrentSeg][0]
                    if seg_histories[iS, iH] < 0:
                        sys.stdout.write(
                            "            segment "
                            + str(iS)
                            + " warped "
                            + str(iH)
                            + " iters ago\n"
                        )
        self.seg_histories = seg_histories[:, :-1].astype(int)
        self.weight_histories = weight_histories
        # weight histories and segment histories go in reverse order, so final current iter is first of 0 index

    def collect_iter_coordinates(self):  # grab coordinates from WE traj_segs folder
        nS = self.nSeg
        westFile = self.fileList[self.westList[0]]
        dataIn = h5py.File(westFile, "a")
        coords = np.zeros((0, 2, self.nAtoms, 3))
        for iS in range(self.nSeg):
            westFile = self.fileList[self.westList[iS]]
            WEfolder = westFile.replace("west.h5", "")
            trajpath = WEfolder + "traj_segs/%06d/%06d" % (self.n_iter, iS)
            coord0 = np.squeeze(
                md.load(
                    trajpath + "/parent.rst7", top=self.reference_structure.topology
                )._xyz
            )
            coord1 = np.squeeze(
                md.load(
                    trajpath + "/seg.rst7", top=self.reference_structure.topology
                )._xyz
            )
            coordT = np.array([coord0, coord1])
            coordT = coordT[np.newaxis, :, :, :]
            coords = np.append(coords, coordT, axis=0)
            try:
                if iS > 0:
                    if self.westList[iS] != self.westList[iS - 1] and iS < nS - 1:
                        dsetName = "/iterations/iter_%08d/auxdata/coord" % int(
                            self.n_iter
                        )
                        try:
                            dset = dataIn.create_dataset(
                                dsetName, np.shape(coords[:-1, :, :, :])
                            )
                            dset[:] = coords[:-1, :, :, :]
                        except:
                            del dataIn[dsetName]
                            dset = dataIn.create_dataset(
                                dsetName, np.shape(coords[:-1, :, :, :])
                            )
                            dset[:] = coords[:-1, :, :, :]
                            sys.stdout.write(
                                "coords exist for iteration "
                                + str(n_iter)
                                + " overwritten\n"
                            )
                        dataIn.close()
                        coords = np.zeros((0, 2, self.nAtoms, 3))
                        coords = np.append(coords, coordT, axis=0)
                        dataIn = h5py.File(westFile, "a")
                    elif iS == nS - 1:
                        dsetName = "/iterations/iter_%08d/auxdata/coord" % int(
                            self.n_iter
                        )
                        try:
                            dset = dataIn.create_dataset(dsetName, np.shape(coords))
                            dset[:] = coords
                        except:
                            del dataIn[dsetName]
                            dset = dataIn.create_dataset(dsetName, np.shape(coords))
                            dset[:] = coords
                            sys.stdout.write(
                                "coords exist for iteration "
                                + str(self.n_iter)
                                + " overwritten\n"
                            )
                        dataIn.close()
            except:
                sys.stdout.write(
                    "error collecting coordinates from "
                    + WEfolder
                    + " , iter "
                    + str(self.n_iter)
                    + " segment "
                    + str(self.segindList[iS])
                    + "\n"
                )

    def get_iter_coordinates(self):  # get iteration final coordinates
        coordList = np.zeros((self.nSeg, self.nAtoms, 3))
        for iS in range(self.nSeg):
            try:
                if iS == 0:
                    westFile = self.fileList[self.westList[iS]]
                    dataIn = h5py.File(westFile, "r")
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                    dset = dataIn[dsetName]
                    coord = dset[:]
                elif self.westList[iS] != self.westList[iS - 1]:
                    dataIn.close()
                    westFile = self.fileList[self.westList[iS]]
                    dataIn = h5py.File(westFile, "r")
                    dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                    dset = dataIn[dsetName]
                    coord = dset[:]
                coordList[iS, :, :] = coord[self.segindList[iS], 1, :, :]
            except:
                sys.stdout.write(
                    "error getting coordinates from "
                    + self.fileList[self.westList[iS]]
                    + " , iter "
                    + str(self.n_iter)
                    + " segment "
                    + str(self.segindList[iS])
                    + "\n"
                )
                coordList[iS, :, :] = np.zeros((self.nAtoms, 3))
                self.coordsExist = False
        self.coordList = coordList

    def get_iter_coordinates0(self):  # get iteration initial coordinates
        coordList = np.zeros((self.nSeg, self.nAtoms, 3))
        for iS in range(self.nSeg):
            if iS == 0:
                westFile = self.fileList[self.westList[iS]]
                dataIn = h5py.File(westFile, "r")
                dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                dset = dataIn[dsetName]
                coord = dset[:]
            elif self.westList[iS] != self.westList[iS - 1]:
                dataIn.close()
                westFile = self.fileList[self.westList[iS]]
                dataIn = h5py.File(westFile, "r")
                dsetName = "/iterations/iter_%08d/auxdata/coord" % int(self.n_iter)
                dset = dataIn[dsetName]
                coord = dset[:]
            coordList[iS, :, :] = coord[self.segindList[iS], 0, :, :]
        self.coordList = coordList

    def get_coordinates(self, first_iter, last_iter):
        self.first_iter = first_iter
        self.last_iter = last_iter
        iters = range(self.first_iter, self.last_iter + 1)
        coordSet = np.zeros((0, self.nAtoms, 3))
        for iter in iters:
            if iter % 50 == 0:
                sys.stdout.write(
                    "    gathering structures from iteration " + str(iter) + "...\n"
                )
            self.get_iter_data(iter)
            self.get_iter_coordinates()
            if self.coordsExist:
                coordSet = np.append(coordSet, self.coordList, axis=0)
        self.coordSet = coordSet

    def get_coordSet(self, last_iter, n_coords):
        last_iter_cluster = last_iter
        i = last_iter_cluster
        numCoords = 0
        coordSet = np.zeros((0, self.nAtoms, 3))
        pcoordSet = np.zeros((0, self.pcoord_ndim))
        while numCoords < n_coords:
            self.get_iter_data(i)
            self.get_iter_coordinates()
            indGood = np.squeeze(np.where(np.sum(np.sum(self.coordList, 2), 1) != 0))
            coordSet = np.append(coordSet, self.coordList[indGood, :, :], axis=0)
            pcoordSet = np.append(pcoordSet, self.pcoord1List[indGood, :], axis=0)
            numCoords = np.shape(coordSet)[0]
            i = i - 1
        self.coordSet = coordSet
        self.pcoordSet = pcoordSet
        first_iter_cluster = i
        self.first_iter = first_iter_cluster
        self.last_iter = last_iter_cluster
        self.n_coords = np.shape(self.coordSet)[0]

    def get_traj_coordinates(self, from_iter, traj_length):
        if traj_length > from_iter:
            traj_length = from_iter - 1
            sys.stdout.write(
                "trajectory length too long: set to " + str(traj_length) + "\n"
            )
        self.get_iter_data(from_iter)
        self.get_seg_histories(traj_length)
        traj_iters = np.zeros((traj_length, self.nSeg, self.nAtoms, 3))
        ic = traj_length - 1
        iH = 0
        nS = self.nSeg
        westList = self.westList.copy()
        for i in range(from_iter, from_iter - traj_length, -1):
            sys.stdout.write(
                "    gathering structures from iteration " + str(i) + "...\n"
            )
            self.get_iter_data(i)
            self.get_iter_coordinates()
            seg_history = self.seg_histories[:, iH]
            seg_history_index = np.zeros(nS).astype(int)
            last_index = np.zeros(nS).astype(
                int
            )  # list of final iterations for warped particles
            for iS in range(nS):
                if seg_history[iS] > 0:
                    seg_history_index[iS] = np.where(
                        np.logical_and(
                            self.segindList == seg_history[iS],
                            self.westList == westList[iS],
                        )
                    )[0][
                        0
                    ]  # segment indexes are local to the westfile, not global for the analysis set
                    last_index[iS] = 0
                elif seg_history[iS] < 0:
                    last_index[iS] = i - (from_iter - traj_length) - 1
            traj_iters[ic, :, :, :] = self.coordList[seg_history_index, :, :]
            ic = ic - 1
            iH = iH + 1
        self.get_iter_data(from_iter)
        traj_iters = np.swapaxes(traj_iters, 0, 1)
        self.trajSet = [None] * self.nSeg
        for iS in range(self.nSeg):
            self.trajSet[iS] = traj_iters[iS, last_index[iS] :, :, :]

    def dimReduce(self):
        # here we can put method to reduce dimensionalitya
        nC = np.shape(self.coordSet)
        nC = nC[0]
        if self.dimReduceMethod == "pca":
            data = self.processCoordinates(self.coordSet)
            self.coordinates = coor.pca(
                data, dim=-1, var_cutoff=0.95, mean=None, stride=1, skip=0
            )
            self.ndim = self.coordinates.dimension()
        if self.dimReduceMethod == "vamp":
            ntraj = len(self.trajSet)
            data = [None] * ntraj
            for itraj in range(ntraj):
                data[itraj] = self.processCoordinates(self.trajSet[itraj])
            self.coordinates = coor.vamp(
                data,
                lag=self.vamp_lag,
                dim=self.vamp_dim,
                scaling=None,
                right=False,
                stride=1,
                skip=0,
            )
            self.ndim = self.coordinates.dimension()
        if self.dimReduceMethod == "none":
            data = self.coordSet.reshape(nC, 3 * self.nAtoms)
            self.coordinates = self.Coordinates()
            self.ndim = 3 * self.nAtoms
            # self.coordinates.transform=self.processCoordinates

    class Coordinates(object):

        # The class "constructor" - It's actually an initializer
        def __init__(self):
            self.explanation = "coordinate object"

        def transform(self, coords):
            return coords

    def processCoordinates(self, coords):
        if self.dimReduceMethod == "none":
            nC = np.shape(coords)
            nC = nC[0]
            ndim = 3 * self.nAtoms
            data = coords.reshape(nC, 3 * self.nAtoms)
            return data
        if self.dimReduceMethod == "pca" or self.dimReduceMethod == "vamp":
            xt = md.Trajectory(xyz=coords, topology=None)
            indCA = self.reference_structure.topology.select("name CA")
            pair1, pair2 = np.meshgrid(indCA, indCA, indexing="xy")
            indUT = np.where(np.triu(pair1, k=1) > 0)
            pairs = np.transpose(np.array([pair1[indUT], pair2[indUT]])).astype(int)
            dist = md.compute_distances(xt, pairs, periodic=True, opt=True)
            return dist

    def reduceCoordinates(self, coords):
        if self.dimReduceMethod == "none":
            nC = np.shape(coords)
            nC = nC[0]
            ndim = 3 * self.nAtoms
            data = coords.reshape(nC, 3 * self.nAtoms)
            return data
        if self.dimReduceMethod == "pca" or self.dimReduceMethod == "vamp":
            coords = self.processCoordinates(coords)
            coords = self.coordinates.transform(coords)
            return coords

    def cluster_coordinates(self, n_clusters):
        self.n_clusters = n_clusters
        nC = np.shape(self.coordSet)
        nC = nC[0]
        if self.dimReduceMethod == "none":
            if self.nAtoms > 1:
                self.clusters = coor.cluster_kmeans(
                    [self.coordSet.reshape(nC, 3 * self.nAtoms)],
                    k=n_clusters,
                    metric="minRMSD",
                )  # ,max_iter=100)
            elif self.nAtoms == 1:
                self.clusters = coor.cluster_kmeans(
                    [self.coordSet.reshape(nC, 3 * self.nAtoms)],
                    k=n_clusters,
                    metric="euclidean",
                )
        if self.dimReduceMethod == "pca" or self.dimReduceMethod == "vamp":
            self.clusters = coor.cluster_kmeans(
                self.coordinates.get_output(), k=n_clusters, metric="euclidean"
            )  # ,max_iter=100)
        self.clusterFile = (
            self.modelName
            + "_clusters_s"
            + str(self.first_iter)
            + "_e"
            + str(self.last_iter)
            + "_nC"
            + str(self.n_clusters)
            + ".h5"
        )
        self.clusters.save(self.clusterFile, save_streaming_chain=True)

    def load_clusters(self, clusterFile):
        self.clusters = pyemma.load(clusterFile)
        self.n_clusters = np.shape(self.clusters.clustercenters)[0]

    def get_iter_fluxMatrix(self, n_iter):
        sys.stdout.write("iteration " + str(n_iter) + ": data \n")
        self.get_iter_data(n_iter)
        if self.n_lag > 0:
            sys.stdout.write("segment histories \n")
            self.get_seg_histories(self.n_lag + 1)
            sys.stdout.write(" transition data...\n")
            self.get_transition_data(self.n_lag)
        elif self.n_lag == 0:
            self.get_transition_data_lag0()
        nT = np.shape(self.transitionWeights)[0]
        indTargetCluster = self.n_clusters + 1
        indBasisCluster = self.n_clusters
        cluster0 = self.clusters.assign(
            self.reduceCoordinates(self.coordPairList[:, :, :, 0])
        )
        cluster1 = self.clusters.assign(
            self.reduceCoordinates(self.coordPairList[:, :, :, 1])
        )
        indTarget1 = np.where(self.is_WE_target(self.pcoord1List))
        if indTarget1[0].size > 0:
            sys.stdout.write("Target1: " + str(indTarget1[0].size) + "\n")
        indBasis0 = np.where(
            self.is_WE_basis(self.pcoord0List)
        )  # needs to fit definition of target in WE
        if indBasis0[0].size > 0:
            sys.stdout.write("Basis0: " + str(indBasis0[0].size) + "\n")
        indBasis1 = np.where(self.is_WE_basis(self.pcoord1List))
        if indBasis1[0].size > 0:
            sys.stdout.write("Basis1: " + str(indBasis1[0].size) + "\n")
        cluster1[indTarget1] = indTargetCluster
        cluster0[indBasis0] = indBasisCluster
        cluster1[indBasis1] = indBasisCluster
        fluxMatrix = coo_matrix(
            (self.transitionWeights, (cluster0, cluster1)),
            shape=(self.n_clusters + 2, self.n_clusters + 2),
        ).todense()
        return fluxMatrix

    def get_pcoord1D_fluxMatrix(self, n_lag, first_iter, last_iter, binbounds):
        self.n_lag = n_lag
        nBins = binbounds.size - 1
        fluxMatrix = np.zeros((nBins, nBins))
        nI = 0
        f = h5py.File(self.modelName + ".h5", "a")
        dsetName = (
            "/s"
            + str(first_iter)
            + "_e"
            + str(last_iter)
            + "_lag"
            + str(n_lag)
            + "_b"
            + str(nBins)
            + "/pcoord1D_fluxMatrix"
        )
        e = dsetName in f
        if not e:
            dsetP = f.create_dataset(dsetName, np.shape(fluxMatrix))
            for iS in range(first_iter + 1, last_iter + 1):
                if n_lag > 0:
                    fluxMatrixI = self.get_iter_pcoord1D_fluxMatrix(iS, binbounds)
                elif n_lag == 0:
                    fluxMatrixI = self.get_iter_pcoord1D_fluxMatrix_lag0(iS, binbounds)
                fluxMatrixI = fluxMatrixI / np.sum(
                    self.weightList
                )  # correct for multiple trees
                fluxMatrix = fluxMatrix + fluxMatrixI
                nI = nI + 1
                dsetP[:] = fluxMatrix / nI
                dsetP.attrs["iter"] = iS
            fluxMatrix = fluxMatrix / nI
        elif e:
            dsetP = f[dsetName]
            fluxMatrix = dsetP[:]
            try:
                nIter = dsetP.attrs["iter"]
            except:
                nIter = first_iter + 1
                fluxMatrix = np.zeros((nBins, nBins))
            nI = 1
            if nIter < last_iter:
                for iS in range(nIter, last_iter + 1):
                    if n_lag > 0:
                        fluxMatrixI = self.get_iter_pcoord1D_fluxMatrix(iS, binbounds)
                    if n_lag == 0:
                        fluxMatrixI = self.get_iter_pcoord1D_fluxMatrix_lag0(
                            iS, binbounds
                        )
                    fluxMatrix = fluxMatrix + fluxMatrixI
                    nI = nI + 1
                    dsetP[:] = fluxMatrix / nI
                    dsetP.attrs["iter"] = iS
                fluxMatrix = fluxMatrix / nI
        f.close()
        self.pcoord1D_fluxMatrix = fluxMatrix

    def get_iter_pcoord1D_fluxMatrix_lag0(self, n_iter, binbounds):
        sys.stdout.write("iteration " + str(n_iter) + ": data \n")
        self.get_iter_data(n_iter)
        nT = np.shape(self.weightList)[0]
        nBins = binbounds.size - 1
        fluxMatrix = np.zeros((nBins, nBins))
        pcoord0 = self.pcoord0List[:, 0]
        pcoord1 = self.pcoord1List[:, 0]
        bins0 = np.digitize(pcoord0, binbounds)
        bins1 = np.digitize(pcoord1, binbounds)
        for iP in range(nT):
            dT0 = bins0[iP] - 1
            dT1 = bins1[iP] - 1
            if np.abs(dT0 - dT1) > 12:
                self.weightList[iP] = 0.0
            fluxMatrix[dT0, dT1] = fluxMatrix[dT0, dT1] + self.weightList[iP]
        return fluxMatrix

    def get_fluxMatrix(self, n_lag, first_iter, last_iter):
        self.n_lag = n_lag
        self.errorWeight = 0.0
        self.errorCount = 0
        fluxMatrix = np.zeros((self.n_clusters + 2, self.n_clusters + 2))
        nI = 0
        fileName = (
            self.modelName
            + "_s"
            + str(first_iter)
            + "_e"
            + str(last_iter)
            + "_lag"
            + str(n_lag)
            + "_clust"
            + str(self.n_clusters)
        )
        f = h5py.File(fileName + ".h5", "a")
        dsetName = "fluxMatrix"
        e = dsetName in f
        if not e:
            dsetP = f.create_dataset(dsetName, np.shape(fluxMatrix))
            dsetP[:] = fluxMatrix
            f.close()
            for iS in range(first_iter + 1, last_iter + 1):
                fluxMatrixI = self.get_iter_fluxMatrix(iS)
                fluxMatrix = fluxMatrix + fluxMatrixI
                nI = nI + 1
                f = h5py.File(fileName + ".h5", "a")
                dsetP = f[dsetName]
                dsetP[:] = fluxMatrix / nI
                dsetP.attrs["iter"] = iS
                f.close()
                sys.stdout.write("getting fluxMatrix iter: " + str(iS) + "\n")
            fluxMatrix = fluxMatrix / nI
        elif e:
            dsetP = f[dsetName]
            fluxMatrix = dsetP[:]
            nIter = dsetP.attrs["iter"]
            f.close()
            nI = 1
            if nIter < last_iter:
                for iS in range(nIter, last_iter + 1):
                    fluxMatrixI = self.get_iter_fluxMatrix(iS)
                    fluxMatrix = fluxMatrix + fluxMatrixI
                    nI = nI + 1
                    f = h5py.File(fileName + ".h5", "a")
                    dsetP = f[dsetName]
                    dsetP[:] = fluxMatrix / nI
                    dsetP.attrs["iter"] = iS
                    f.close()
                    sys.stdout.write("getting fluxMatrix iter: " + str(iS) + "\n")
                fluxMatrix = fluxMatrix / nI
        f.close()
        self.fluxMatrixRaw = fluxMatrix

    def organize_fluxMatrix(self):  # processes raw fluxMatrix
        nT = np.shape(self.coordSet)
        nT = nT[0]
        dtraj = self.clusters.assign(self.reduceCoordinates(self.coordSet))
        indTargetCluster = self.n_clusters + 1  # Target at -1
        indBasisCluster = self.n_clusters  # basis at -2
        indBasisOrig = indBasisCluster
        # targetRMSD=self.get_reference_rmsd(self.coordSet[:,:,:])
        # basisRMSD=self.get_basis_rmsd(self.coordSet[:,:,:])
        # indTarget=np.where(targetRMSD<self.target_rmsd)
        # indBasis=np.where(basisRMSD<self.basis_rmsd)
        # dtraj[indTarget]=indTargetCluster
        # dtraj[indBasis]=indBasisCluster
        indData = np.ones(self.n_clusters + 2)
        targetRMSD_centers = np.zeros(self.n_clusters + 2)
        # targetRMSD_centers[indTargetCluster]=self.target_rmsd
        targetRMSD_centers[indTargetCluster] = self.WEtargetp1
        # targetRMSD_centers[indBasisCluster]=self.get_reference_rmsd(self.basis_coords)
        targetRMSD_centers[indBasisCluster] = self.WEbasisp1_min
        nTraps = 1000
        fluxMatrixTraps = self.fluxMatrixRaw.copy()
        while nTraps > 0:
            nTraps = 0
            for iC in range(self.n_clusters):
                ind = np.where(dtraj == iC)
                if np.shape(ind)[1] == 0:
                    indData[iC] = 0
                elif np.shape(ind)[1] > 0:
                    # targetRMSD_centers[iC]=np.mean(self.get_reference_rmsd(self.coordSet[ind[0],:,:]))
                    targetRMSD_centers[iC] = np.mean(self.pcoordSet[ind[0], 0])
                statesum = np.sum(fluxMatrixTraps[:, iC]) + np.sum(
                    fluxMatrixTraps[iC, :]
                )
                if statesum == 0.0:
                    indData[iC] = 0
                if statesum > 0:
                    indNotSelf = np.setdiff1d(range(self.n_clusters), iC)
                    fromSum = np.sum(fluxMatrixTraps[iC, indNotSelf])
                    toSum = np.sum(fluxMatrixTraps[indNotSelf, iC])
                    if fromSum == 0.0 or toSum == 0.0:
                        nTraps = nTraps + 1
                        indData[iC] = 0
                        fluxMatrixTraps[:, iC] = 0.0
                        fluxMatrixTraps[iC, :] = 0.0
            indData[indBasisCluster] = 1
            indData[indTargetCluster] = 1
        indData = np.squeeze(np.where(indData > 0))
        fluxMatrix = self.fluxMatrixRaw[indData, :]
        fluxMatrix = fluxMatrix[:, indData]
        targetRMSD_centers = targetRMSD_centers[indData]
        indp1 = np.argsort(targetRMSD_centers)
        self.targetRMSD_centers = targetRMSD_centers[indp1]
        fluxMatrix = fluxMatrix[indp1, :]
        fluxMatrix = fluxMatrix[:, indp1]
        self.fluxMatrix = fluxMatrix / np.sum(
            fluxMatrix
        )  # average weight transitioning or staying put should be 1
        originalClusters = indData[indp1]
        self.indBasis = np.where(originalClusters == indBasisCluster)[0]
        self.indTargets = np.where(originalClusters == indTargetCluster)[0]
        self.originalClusters = originalClusters
        self.binCenters = targetRMSD_centers[indp1]
        self.nBins = np.shape(self.binCenters)[0]

    def get_model_clusters(
        self,
    ):  # define new clusters from organized flux matrix corresponding to model
        clustercenters = np.zeros((self.n_clusters + 2, self.ndim))
        clustercenters[0 : self.n_clusters, :] = self.clusters.clustercenters
        if self.dimReduceMethod == "none":
            coords = np.array([self.basis_coords, self.reference_coord])
            clustercenters[self.n_clusters :, :] = self.reduceCoordinates(
                coords
            )  # add in basis and target
            self.model_clusters = clustering.AssignCenters(
                self.reduceCoordinates(clustercenters[self.originalClusters, :]),
                metric="euclidean",
                stride=1,
                n_jobs=None,
                skip=0,
            )
        if self.dimReduceMethod == "pca" or self.dimReduceMethod == "vamp":
            coords = np.array(
                [
                    self.reduceCoordinates(self.basis_coords),
                    self.reduceCoordinates(self.reference_coord),
                ]
            )
            clustercenters[self.n_clusters :, :] = np.squeeze(
                coords
            )  # add in basis and target
            self.model_clusters = clustering.AssignCenters(
                clustercenters[self.originalClusters, :],
                metric="euclidean",
                stride=1,
                n_jobs=None,
                skip=0,
            )

    def get_Tmatrix(self):
        Mt = self.fluxMatrix.copy()
        nR = np.shape(Mt)
        sM = np.sum(Mt, 1)
        for iR in range(nR[0]):
            if sM[iR] > 0:
                Mt[iR, :] = Mt[iR, :] / sM[iR]
            if sM[iR] == 0.0:
                Mt[iR, iR] = 1.0
        # make steady state matrix #first sink
        sinkBins = self.indTargets  # np.where(avBinPnoColor==0.0)
        nsB = np.shape(sinkBins)
        nsB = nsB[0]
        sinkRates = np.zeros((1, self.nBins))
        sinkRates[0, self.indBasis] = 1.0 / self.indBasis.size
        Mss = Mt.copy()
        Mss[sinkBins, :] = np.tile(sinkRates, (nsB, 1))
        self.Tmatrix = Mss

    def get_eqTmatrix(self):
        Mt = self.fluxMatrix.copy()
        n = np.shape(Mt)[0]
        indSpace = np.arange(n).astype(int)
        indSpace = np.setdiff1d(indSpace, np.append(self.indTargets, self.indBasis))
        Mt = Mt[indSpace, :]
        Mt = Mt[:, indSpace]
        nR = np.shape(Mt)
        sM = np.sum(Mt, 1)
        for iR in range(nR[0]):
            if sM[iR] > 0:
                Mt[iR, :] = Mt[iR, :] / sM[iR]
            if sM[iR] == 0.0:
                Mt[iR, iR] = 1.0
        self.Tmatrix = Mt

    def get_steady_state_algebraic(self):
        n = np.shape(self.Tmatrix)[0]
        w, v = np.linalg.eig(np.transpose(self.Tmatrix))
        pSS = np.real(v[:, np.argmax(np.real(w))])
        pSS = pSS / np.sum(pSS)
        self.pSS = pSS

    def get_steady_state_matrixpowers(self, conv):
        max_iters = 10000
        Mt = self.Tmatrix.copy()
        dconv = 1.0e100
        N = 1
        pSS = np.mean(Mt, 0)
        pSSp = np.ones_like(pSS)
        while dconv > conv and N < max_iters:
            Mt = np.matmul(self.Tmatrix, Mt)
            N = N + 1
            if N % 10 == 0:
                pSS = np.mean(Mt, 0)
                pSS = pSS / np.sum(pSS)
                dconv = np.sum(np.abs(pSS - pSSp))
                pSSp = pSS.copy()
                sys.stdout.write("N=" + str(N) + " dconv: " + str(dconv) + "\n")
                self.pSS = pSS.copy()

    def get_steady_state_target_flux(self):
        Mss = self.Tmatrix
        pSS = np.squeeze(np.array(self.pSS))
        self.lagtime = self.tau * (self.n_lag + 1)
        nTargets = self.indTargets.size
        indNotTargets = np.setdiff1d(range(self.nBins), self.indTargets)
        Jt = 0.0
        for j in range(nTargets):
            jj = self.indTargets[j]
            Jt = Jt + np.sum(
                np.multiply(
                    pSS[indNotTargets],
                    np.squeeze(
                        np.array(Mss[indNotTargets, jj * np.ones_like(indNotTargets)])
                    ),
                )
            )
        self.JtargetSS = Jt / self.lagtime

    def evolve_probability(
        self, nEvolve, nStore
    ):  # iterate nEvolve times, storing every nStore iterations, initial condition at basis
        nIterations = np.ceil(nEvolve / nStore).astype(int) + 1
        self.nEvolve = nEvolve
        self.nStore = nStore
        Mss = self.Tmatrix
        nBins = self.nBins
        binCenters = self.binCenters
        probBasis = np.zeros((1, self.nBins))
        probBasis[0, self.indBasis] = 1.0
        pSS = probBasis.copy()
        pSSPrev = np.ones_like(pSS)
        iT = 1
        probTransient = np.zeros((nIterations, nBins))  # while dConv>.00001:
        probTransient[0, :] = probBasis
        for i in range(nEvolve):
            pSS = np.matmul(pSS, Mss)
            dConv = np.sum(np.abs(pSS - pSSPrev))
            pSSPrev = pSS.copy()
            if i % nStore == 0:
                sys.stdout.write("SS conv: " + str(dConv) + " iter: " + str(i))
                try:
                    plt.plot(
                        binCenters,
                        np.squeeze(pSS),
                        "-",
                        color=plt.cm.Greys(float(i) / float(nEvolve)),
                    )
                    plt.yscale("log")
                except:
                    try:
                        plt.plot(
                            binCenters,
                            pSS.A1,
                            "-",
                            color=plt.cm.Greys(float(i) / float(nEvolve)),
                        )
                    except:
                        pass
                probTransient[iT, :] = np.squeeze(pSS)
                iT = iT + 1
        probTransient = probTransient[0:iT, :]
        self.probTransient = probTransient
        pSS = np.squeeze(np.array(pSS))
        self.pSS = pSS / np.sum(pSS)
        try:
            plt.pause(4)
            plt.close()
        except:
            pass

    def evolve_probability2(
        self, nEvolve, nStore
    ):  # iterate nEvolve times, storing every nStore iterations, initial condition spread for everything at RMSD higher than basis
        nIterations = np.ceil(nEvolve / nStore).astype(int) + 1
        self.nEvolve = nEvolve
        self.nStore = nStore
        Mss = self.Tmatrix
        nBins = self.nBins
        binCenters = self.binCenters
        probBasis = np.zeros((1, self.nBins))
        probBasis[
            0, self.indBasis[0] :
        ] = 1.0  # assign initial probability to everything at RMSD higher than the basis, for case when nothing observed leaving exact basis
        probBasis = probBasis / np.sum(probBasis)
        pSS = probBasis.copy()
        pSSPrev = np.ones_like(pSS)
        iT = 1
        probTransient = np.zeros((nIterations, nBins))  # while dConv>.00001:
        probTransient[0, :] = probBasis
        for i in range(nEvolve):
            pSS = np.matmul(pSS, Mss)
            dConv = np.sum(np.abs(pSS - pSSPrev))
            pSSPrev = pSS.copy()
            if i % nStore == 0:
                sys.stdout.write("SS conv: " + str(dConv) + " iter: " + str(i))
                try:
                    plt.plot(
                        binCenters,
                        np.squeeze(pSS),
                        "-",
                        color=plt.cm.Greys(float(i) / float(nEvolve)),
                    )
                    plt.yscale("log")
                except:
                    try:
                        plt.plot(
                            binCenters,
                            pSS.A1,
                            "-",
                            color=plt.cm.Greys(float(i) / float(nEvolve)),
                        )
                    except:
                        pass
                # plt.ylim([1e-100,1])
                # plt.title(str(iT)+' of '+str(nIterations))
                # plt.pause(.1)
                probTransient[iT, :] = np.squeeze(pSS)
                iT = iT + 1
        probTransient = probTransient[0:iT, :]
        self.probTransient = probTransient
        pSS = np.squeeze(np.array(pSS))
        self.pSS = pSS / np.sum(pSS)
        try:
            plt.pause(4)
            plt.close()
        except:
            pass

    def evolve_probability_from_initial(
        self, p0, nEvolve, nStore
    ):  # iterate nEvolve times, storing every nStore iterations, initial condition provided
        nIterations = np.ceil(nEvolve / nStore).astype(int) + 1
        self.nEvolve = nEvolve
        self.nStore = nStore
        Mss = self.Tmatrix
        nBins = self.nBins
        binCenters = self.binCenters
        probBasis = np.zeros((1, self.nBins))
        if np.shape(probBasis)[1] == np.shape(p0)[0]:
            probBasis[0, :] = p0
        else:
            probBasis = p0
        pSS = probBasis.copy()
        pSSPrev = np.ones_like(pSS)
        iT = 1
        probTransient = np.zeros((nIterations, nBins))  # while dConv>.00001:
        probTransient[0, :] = probBasis
        for i in range(nEvolve):
            pSS = np.matmul(pSS, Mss)
            dConv = np.sum(np.abs(pSS - pSSPrev))
            pSSPrev = pSS.copy()
            if i % nStore == 0:
                sys.stdout.write("SS conv: " + str(dConv) + " iter: " + str(i))
                try:
                    plt.plot(
                        binCenters,
                        np.squeeze(pSS),
                        "-",
                        color=plt.cm.Greys(float(i) / float(nEvolve)),
                    )
                    plt.yscale("log")
                except:
                    try:
                        plt.plot(
                            binCenters,
                            pSS.A1,
                            "-",
                            color=plt.cm.Greys(float(i) / float(nEvolve)),
                        )
                    except:
                        pass
                probTransient[iT, :] = np.squeeze(pSS)
                iT = iT + 1
        probTransient = probTransient[0:iT, :]
        self.probTransient = probTransient
        pSS = np.squeeze(np.array(pSS))
        self.pSS = pSS / np.sum(pSS)
        try:
            plt.pause(4)
            plt.close()
        except:
            pass

    def get_flux(self):
        J = np.zeros_like(self.binCenters)
        nBins = np.shape(self.binCenters)[0]
        fluxMatrix = self.fluxMatrix.copy()
        for i in range(0, nBins - 1):
            indBack = range(i + 1)
            indForward = range(i + 1, nBins)
            JR = 0.0
            JF = 0.0
            for j in indBack:
                JR = JR + np.sum(fluxMatrix[indForward, j * np.ones_like(indForward)])
            for j in indForward:
                JF = JF + np.sum(fluxMatrix[indBack, j * np.ones_like(indBack)])
            J[i] = JR - JF
            self.J = J
            sys.stdout.write(str(i))

    def get_flux_committor(self):
        J = np.zeros_like(self.binCenters)
        nBins = np.shape(self.binCenters)[0]
        fluxMatrix = self.fluxMatrix.copy()
        indq = np.argsort(np.squeeze(1.0 - self.q))
        fluxMatrix = fluxMatrix[indq, :]
        fluxMatrix = fluxMatrix[:, indq]
        for i in range(0, nBins - 1):
            indBack = range(i + 1)
            indForward = range(i + 1, nBins)
            JR = 0.0
            JF = 0.0
            for j in indBack:
                JR = JR + np.sum(fluxMatrix[indForward, j * np.ones_like(indForward)])
            for j in indForward:
                JF = JF + np.sum(fluxMatrix[indBack, j * np.ones_like(indBack)])
            J[i] = JR - JF
            self.Jq = J / model.tau
            sys.stdout.write("%s " % i)

    def plot_flux_committor(self, nwin):
        Jq_av = self.Jq.copy()
        Jq_std = np.zeros_like(Jq_av)
        q_av = np.zeros_like(Jq_av)
        indq = np.argsort(np.squeeze(1.0 - self.q))
        for i in range(nBins - 1, nwin - 1, -1):
            iav = i - nwin
            ind = range(i - nwin, i)
            Jq_av[iav] = np.mean(model.Jq[ind])
            Jq_std[iav] = np.std(model.Jq[ind])
            q_av[iav] = np.mean(model.q[indq[ind]])
        fig = plt.figure(figsize=(8, 6))
        ax = fig.add_subplot(111)
        indPlus = np.where(Jq_av > 0.0)
        indMinus = np.where(Jq_av < 0.0)
        ax.plot(
            q_av[indMinus],
            -np.squeeze(Jq_av[indMinus]),
            "<",
            color="black",
            linewidth=2,
            markersize=10,
            label="flux toward unfolded",
        )
        ax.plot(
            q_av[indPlus],
            np.squeeze(Jq_av[indPlus]),
            ">",
            color="black",
            linewidth=2,
            markersize=10,
            label="flux toward folded",
        )
        plt.yscale("log")
        plt.xscale("log")
        plt.xlabel("Committor")
        plt.ylabel("Flux (weight/second")
        fig.savefig(self.modelName + "flux_committor.pdf")
        plt.pause(1)

    def plot_flux(self):
        tau = 10.0e-12
        J = self.J / tau
        binCenters = self.binCenters
        fig = plt.figure(figsize=(8, 6))
        ax = fig.add_subplot(111)
        indPlus = np.where(J > 0.0)
        indMinus = np.where(J < 0.0)
        ax.plot(
            binCenters[indPlus],
            np.squeeze(J[indPlus]),
            "ko",
            linewidth=2,
            markersize=10,
            label="flux toward folded",
        )  # ,color=plt.cm.Greys(float(iStep)/float(nStepFrames)))
        ax.plot(
            binCenters[indMinus],
            -np.squeeze(J[indMinus]),
            "ro",
            linewidth=2,
            markersize=10,
            label="flux toward unfolded",
        )  # ,color=plt.cm.Reds(float(iStep)/float(nStepFrames)))
        plt.yscale("log")
        plt.ylabel("flux (weight/second)", fontsize=12)
        plt.xlabel("RMSD ($\AA$)", fontsize=12)
        plt.title(
            "Flux Run 1-30 Iter " + str(self.first_iter) + "-" + str(self.last_iter)
        )
        plt.legend(loc="lower right")
        plt.pause(1)
        fig.savefig(
            "flux_s" + str(self.first_iter) + "_e" + str(self.last_iter) + ".png"
        )

    def evolve_target_flux(self):
        Mss = self.Tmatrix
        probTransient = self.probTransient
        nT = np.shape(probTransient)[0]
        Jtarget = np.zeros(nT)
        self.lagtime = self.tau * (self.n_lag + 1)
        nTargets = self.indTargets.size
        indNotTargets = np.setdiff1d(range(self.nBins), self.indTargets)
        JtargetTimes = np.zeros(nT)
        for iT in range(nT):
            Jt = 0.0
            for j in range(nTargets):
                jj = self.indTargets[j]
                Jt = Jt + np.sum(
                    np.multiply(
                        probTransient[iT, indNotTargets],
                        Mss[indNotTargets, jj * np.ones_like(indNotTargets)],
                    )
                )
            Jtarget[iT] = Jt
            JtargetTimes[iT] = iT * self.nStore * self.lagtime
        self.Jtarget = Jtarget / self.lagtime
        self.JtargetTimes = JtargetTimes

    def get_hflux(self, conv):
        convh = conv
        convf = conv
        max_iters = 50000
        nTargets = self.indTargets.size
        indNotTargets = np.setdiff1d(range(self.nBins), self.indTargets)
        Mt = self.Tmatrix.copy()
        dconvh = 1.0e100
        dconvf = 1.0e100
        fTotal = np.zeros((self.nBins, 1))
        fSSp = 0.0
        hp = np.zeros_like(fTotal)
        N = 1
        while dconvh > convh or dconvf > convf and N < max_iters:
            f = np.zeros((self.nBins, 1))
            for i in range(self.nBins):
                Jt = 0.0
                Pt = Mt[i, :]
                for j in range(nTargets):
                    jj = self.indTargets[j]
                    Jt = Jt + np.sum(
                        np.multiply(
                            Pt[0, indNotTargets],
                            Mt[indNotTargets, jj * np.ones_like(indNotTargets)],
                        )
                    )
                f[i, 0] = Jt / self.tau
            fTotal = fTotal + f
            fSS = np.mean(f[indNotTargets, 0])
            ht = fTotal - N * fSS
            dconvh = np.max(np.abs(hp - ht)) / np.max(ht)
            dconvf = np.abs(fSS - fSSp) / fSS
            sys.stdout.write(
                "N="
                + str(N)
                + " dh: "
                + str(dconvh)
                + " df: "
                + str(dconvf)
                + " Jss:"
                + str(fSS)
                + "\n"
            )
            hp = ht.copy()
            fSSp = fSS
            self.h = ht.copy()
            Mt = np.matmul(Mt, self.Tmatrix)
            N = N + 1

    def get_model_aristoffian(self):
        kh = np.matmul(self.Tmatrix, self.h)
        kh_sq = np.power(kh, 2)
        hsq = np.power(self.h, 2)
        k_hsq = np.matmul(self.Tmatrix, hsq)
        varh = k_hsq - kh_sq
        # val=np.sqrt(varh)
        self.varh = varh
        self.kh = kh

    def get_model_steady_state_aristoffian(self):
        nB = int(self.nB)
        if self.binMethod == "adaptive":
            self.kh_clusters = coor.cluster_kmeans(self.kh, k=nB, metric="euclidean")
            khbins_centers = self.kh_clusters.clustercenters[:, 0]
            khbins_centers_unique, ind_unique = np.unique(
                khbins_centers, return_index=True
            )
            if khbins_centers_unique.size != nB:
                khbins = np.squeeze(
                    np.linspace(np.min(self.kh), np.max(self.kh), nB + 1)
                )  # equal spacing if not enough for k-means
                khbins_centers = 0.5 * (khbins[1:] + khbins[0:-1])
                self.kh_clusters = clustering.AssignCenters(
                    khbins_centers[:, np.newaxis],
                    metric="euclidean",
                    stride=1,
                    n_jobs=None,
                    skip=0,
                )
        elif self.binMethod == "uniform":
            khbins = np.squeeze(
                np.linspace(np.min(self.kh), np.max(self.kh), nB + 1)
            )  # equal spacing if not enough for k-means
            khbins_centers = 0.5 * (khbins[1:] + khbins[0:-1])
            self.kh_clusters = clustering.AssignCenters(
                khbins_centers[:, np.newaxis],
                metric="euclidean",
                stride=1,
                n_jobs=None,
                skip=0,
            )
        elif self.binMethod == "log_uniform":
            transformedBins = np.geomspace(
                np.abs(np.min(self.kh)) / np.max(self.kh),
                1.0 + 2.0 * np.abs(np.min(self.kh)) / np.max(self.kh),
                self.nB + 1,
            )
            khbins_binEdges_log = transformedBins * np.max(self.kh) - 2.0 * np.abs(
                np.min(self.kh)
            )
            khbins = khbins_binEdges_log  # equal log-spacing
            khbins_centers = 0.5 * (khbins[1:] + khbins[0:-1])
            self.kh_clusters = clustering.AssignCenters(
                khbins_centers[:, np.newaxis],
                metric="euclidean",
                stride=1,
                n_jobs=None,
                skip=0,
            )
        elif self.binMethod == "optimized":
            try:
                khbins_centers = np.loadtxt("khbins_binCenters.dat")
                self.kh_clusters = clustering.AssignCenters(
                    khbins_centers[:, np.newaxis],
                    metric="euclidean",
                    stride=1,
                    n_jobs=None,
                    skip=0,
                )
            except:
                sys.stdout.write(
                    "khbins (khbins_binCenters.dat) not found: initializing\n"
                )
                self.get_initial_khbins_equalAlloc()
                self.kh_clusters = clustering.AssignCenters(
                    khbins_centers[:, np.newaxis],
                    metric="euclidean",
                    stride=1,
                    n_jobs=None,
                    skip=0,
                )
            if not hasattr(self, "kh_clusters"):
                sys.stdout.write("giving up: log uniform kh bins")
                self.get_initial_khbins()
            khbins_centers = self.kh_clusters.clustercenters[:, 0]
        dtraj_kh_clusters = self.kh_clusters.assign(self.kh)
        alloc = np.zeros(
            nB
        )  # get bin objective function, value and allocation over set of bins
        value = np.zeros(nB)
        bin_kh_var = np.zeros(nB)
        for i in range(nB):
            indBin = np.where(dtraj_kh_clusters == i)
            if indBin[0].size == 0:
                alloc[i] = 0.0
                bin_kh_var[i] = 0.0
            else:
                n = indBin[0].size
                bin_kh_var[i] = np.var(self.kh[indBin])
                wt = np.sum(self.pSS[indBin])
                vw = np.sum(np.multiply(self.pSS[indBin] / wt, self.varh[indBin]))
                alloc[i] = wt * (vw) ** 0.5
                value[i] = vw ** 0.5
        if self.allocationMethod == "uniform":
            alloc = np.ones_like(alloc)
        alloc = alloc / np.sum(alloc)
        self.alloc = alloc
        # base_walkers=self.min_walkers*np.ones_like(alloc)
        # nBase=np.sum(base_walkers)
        # nAdapt=self.nW-nBase
        # if nAdapt<0:
        #    nAdapt=0
        # walkers=np.round(alloc*nAdapt)
        # walkers=walkers+base_walkers
        # indZero=np.where(walkers==0.0)
        # walkers[indZero]=1.0
        # walkers=walkers.astype(int)
        # binEdges=np.zeros(self.nB+1)
        # binEdges[0]=-np.inf
        # binEdges[-1]=np.inf
        # ind=np.argsort(self.kh_clusters.clustercenters[:,0]) #note sorting makes kh_clusters indexes differen
        # self.khbins_binCenters=self.kh_clusters.clustercenters[ind,0]
        # binEdges[1:-1]=0.5*(self.khbins_binCenters[1:]+self.khbins_binCenters[0:-1])
        # self.khbins_binEdges=binEdges
        # self.walkers_per_bin=walkers[ind]
        # self.bin_kh_var=bin_kh_var[ind]
        gamma = self.alloc.copy()  # asymptotic particle distribution in bins
        # asymptotic particle distribution after mutation
        rho = np.zeros_like(gamma)
        rhov = np.zeros((self.nB, self.nB))
        for v in range(self.nB):
            indBinv = np.where(dtraj_kh_clusters == v)
            wv = np.sum(self.pSS[indBinv])
            sys.stdout.write("sum v: " + str(v) + "\n")
            for u in range(self.nB):
                indBinu = np.where(dtraj_kh_clusters == u)
                for p in indBinv[0]:
                    for q in indBinu[0]:
                        rhov[u, v] = (
                            rhov[u, v]
                            + self.alloc[v] * (self.pSS[p] / wv) * self.Tmatrix[p, q]
                        )
        rho = np.sum(rhov, 1)
        pOccupied = 1.0 - np.power(1.0 - rho, self.nW)
        nOccupied = nB - np.sum(np.power(1.0 - rho, self.nW))
        nAdditional = (self.nW - nOccupied) * self.alloc
        nT = nAdditional + pOccupied
        # nT=np.zeros(nB)
        # for i in range(nB):
        #    nT[i]=np.max(np.array([1,nAdditional[i]+pOccupied[i]]))
        bin_mutV = np.zeros(nB)
        bin_selV = np.zeros(nB)
        for i in range(nB):
            indBin = np.where(dtraj_kh_clusters == i)
            wi = np.sum(self.pSS[indBin])
            bin_mutV[i] = ((wi ** 2) / (nT[i])) * np.sum(
                np.multiply(self.pSS[indBin] / wi, self.varh[indBin])
            )
            bin_selV[i] = ((wi ** 2) / (nT[i])) * np.sum(
                np.multiply(self.pSS[indBin] / wi, np.power(self.kh[indBin], 2))
                - np.power(np.multiply(self.pSS[indBin] / wi, self.kh[indBin]), 2)
            )
        self.binObjective = np.sum(bin_mutV + bin_selV)
        binEdges = np.zeros(self.nB + 1)
        binEdges[0] = -np.inf
        binEdges[-1] = np.inf
        ind = np.argsort(
            self.kh_clusters.clustercenters[:, 0]
        )  # note sorting makes kh_clusters indexes different
        self.khbins_binCenters = self.kh_clusters.clustercenters[ind, 0]
        binEdges[1:-1] = 0.5 * (
            self.khbins_binCenters[1:] + self.khbins_binCenters[0:-1]
        )
        self.khbins_binEdges = binEdges
        # self.walkers_per_bin=walkers[ind]
        self.bin_kh_var = bin_kh_var[ind]
        base_walkers = self.min_walkers * np.ones_like(alloc)
        nBase = nOccupied  # estimated from occupied bins a la Aristoff notes, was np.sum(base_walkers)
        nAdapt = self.nW - nBase
        if nAdapt < 0:
            nAdapt = 0
        walkers = np.round(alloc * nAdapt)
        walkers = walkers + base_walkers
        indZero = np.where(walkers == 0.0)
        walkers[indZero] = 1.0
        walkers = walkers.astype(int)
        self.walkers_per_bin = walkers[ind]
        self.bin_mutV = bin_mutV[ind]
        self.bin_selV = bin_selV[ind]
        self.nOccupancySS = nT[ind]
        self.nOccupied = nOccupied
        self.nAdapt = nAdapt
        self.rhomutation = rho[ind]
        self.value = value

    def get_initial_khbins(self):  # log-uniform kh bins
        transformedBins = np.geomspace(
            np.abs(np.min(self.kh)) / np.max(self.kh),
            1.0 + 2.0 * np.abs(np.min(self.kh)) / np.max(self.kh),
            self.nB + 1,
        )
        khbins_binEdges_log = transformedBins * np.max(self.kh) - 2.0 * np.abs(
            np.min(self.kh)
        )
        khbins = khbins_binEdges_log  # equal log-spacing
        khbins_centers = 0.5 * (khbins[1:] + khbins[0:-1])
        self.kh_clusters = clustering.AssignCenters(
            khbins_centers[:, np.newaxis],
            metric="euclidean",
            stride=1,
            n_jobs=None,
            skip=0,
        )
        binEdges = np.zeros(self.nB + 1)
        binEdges[0] = -np.inf
        binEdges[-1] = np.inf
        ind = np.argsort(
            self.kh_clusters.clustercenters[:, 0]
        )  # note sorting makes kh_clusters indexes different
        self.khbins_binCenters = self.kh_clusters.clustercenters[ind, 0]
        binEdges[1:-1] = 0.5 * (
            self.khbins_binCenters[1:] + self.khbins_binCenters[0:-1]
        )
        self.khbins_binEdges = binEdges
        np.savetxt("khbins_binCenters.dat", self.khbins_binCenters)

    def get_initial_khbins_equalAlloc(self):  # kh bins approximately of equal value
        if not hasattr(self, "kh"):
            self.get_model_aristoffian()
        binMethod_use = self.binMethod
        allocationMethod_use = self.allocationMethod
        nB_use = self.nB
        self.binMethod = "uniform"
        self.allocationMethod = "adaptive"
        points = np.linspace(0, 1, self.nB)
        # resN=np.round(abs(np.max(self.kh)/np.min(np.abs(self.kh)))).astype(int)
        resN = 10000
        self.nB = resN
        self.get_model_steady_state_aristoffian()
        dist = self.alloc.copy()
        dist = dist / np.sum(dist)
        dist = np.cumsum(dist)
        dist_unique, ind_unique = np.unique(dist, return_index=True)
        kh_unique = self.khbins_binCenters[ind_unique]
        xB = np.zeros_like(points)
        for i in range(xB.size):
            indm = np.argmin(np.abs(dist_unique - points[i]))
            xB[i] = kh_unique[indm]
            dist_unique[indm] = np.inf
        khbins_centers = xB.copy()
        self.nB = nB_use
        self.binMethod = binMethod_use
        self.allocationMethod = allocationMethod_use
        self.kh_clusters = clustering.AssignCenters(
            khbins_centers[:, np.newaxis],
            metric="euclidean",
            stride=1,
            n_jobs=None,
            skip=0,
        )
        binEdges = np.zeros(self.nB + 1)
        binEdges[0] = -np.inf
        binEdges[-1] = np.inf
        ind = np.argsort(
            self.kh_clusters.clustercenters[:, 0]
        )  # note sorting makes kh_clusters indexes different
        self.khbins_binCenters = self.kh_clusters.clustercenters[ind, 0]
        binEdges[1:-1] = 0.5 * (
            self.khbins_binCenters[1:] + self.khbins_binCenters[0:-1]
        )
        self.khbins_binEdges = binEdges
        np.savetxt("khbins_binCenters.dat", self.khbins_binCenters)

    def get_bin_kh_var(self, x):
        nB = self.nB
        self.kh_clusters = clustering.AssignCenters(
            x[:, np.newaxis], metric="euclidean", stride=1, n_jobs=None, skip=0
        )
        dtraj_kh_clusters = self.kh_clusters.assign(self.kh)
        # alloc=np.zeros(nB) #get bin objective function, value and allocation over set of bins
        bin_kh_var = np.zeros(nB)
        for i in range(nB):
            indBin = np.where(dtraj_kh_clusters == i)
            if indBin[0].size == 0:
                # alloc[i]=0.0
                bin_kh_var[i] = 0.0
            else:
                n = indBin[0].size
                bin_kh_var[i] = np.var(self.kh[indBin])
                # wt=np.sum(self.pSS[indBin])
                # vw=np.sum(np.multiply(self.pSS[indBin]/wt,self.varh[indBin]))
                # alloc[i]=wt*(vw)**.5
        self.bin_kh_var = bin_kh_var
        self.total_bin_kh_var = np.sum(bin_kh_var)
        return self.total_bin_kh_var

    def get_bin_total_var(self, x):
        nB = self.nB
        self.kh_clusters = clustering.AssignCenters(
            x[:, np.newaxis], metric="euclidean", stride=1, n_jobs=None, skip=0
        )
        self.binMethod = "optimized"
        self.get_model_steady_state_aristoffian()
        return self.binObjective

    def get_iter_aristoffian(self, iter):
        self.get_iter_data(iter)
        if not hasattr(self, "model_clusters"):
            self.get_model_clusters()
        #        if self.pcoord_is_kh:
        # wt=np.sum(self.pSS[indBin])
        # vw=np.sum(np.multiply(self.pSS[indBin]/wt,self.varh[indBin]))
        # alloc[i]=wt*(vw)**.5
        #            self.khList=np.array(self.pcoord1List[:,1]) #kh is pcoord 2 from optimized WE sims
        #            self.khList=self.khList[:,np.newaxis]
        #        else:
        self.get_iter_coordinates()
        dtraj_iter = self.model_clusters.assign(self.reduceCoordinates(self.coordList))
        kh_iter = self.kh[dtraj_iter]
        self.khList = np.array(kh_iter[:, 0])  # get k-means bins defined over walkers
        nB = self.nB
        khList_unique = np.unique(self.khList)
        if khList_unique.size > 2.0 * nB and self.binMethod == "adaptive":
            self.kh_clusters = coor.cluster_kmeans(
                khList_unique, k=nB, metric="euclidean"
            )
            khbins_centers = self.kh_clusters.clustercenters[:, 0]
            khbins_centers_unique, ind_unique = np.unique(
                khbins_centers, return_index=True
            )
            if khbins_centers_unique.size != nB:
                khbins = np.squeeze(
                    np.linspace(np.min(self.kh), np.max(self.kh), nB + 1)
                )  # equal spacing if not enough for k-means
                khbins_centers = 0.5 * (khbins[1:] + khbins[0:-1])
                self.kh_clusters = clustering.AssignCenters(
                    khbins_centers[:, np.newaxis],
                    metric="euclidean",
                    stride=1,
                    n_jobs=None,
                    skip=0,
                )
        elif self.binMethod == "uniform":
            khbins = np.squeeze(
                np.linspace(np.min(self.kh), np.max(self.kh), nB + 1)
            )  # equal spacing if not enough for k-means
            khbins_centers = 0.5 * (khbins[1:] + khbins[0:-1])
            self.kh_clusters = clustering.AssignCenters(
                khbins_centers[:, np.newaxis],
                metric="euclidean",
                stride=1,
                n_jobs=None,
                skip=0,
            )
        elif self.binMethod == "log_uniform":
            transformedBins = np.geomspace(
                np.abs(np.min(self.kh)) / np.max(self.kh),
                1.0 + 2.0 * np.abs(np.min(self.kh)) / np.max(self.kh),
                self.nB,
            )
            khbins_binEdges_log = transformedBins * np.max(self.kh) - 2.0 * np.abs(
                np.min(self.kh)
            )
            khbins = khbins_binEdges_log  # equal log-spacing
            khbins_centers = 0.5 * (khbins[1:] + khbins[0:-1])
            self.kh_clusters = clustering.AssignCenters(
                khbins_centers[:, np.newaxis],
                metric="euclidean",
                stride=1,
                n_jobs=None,
                skip=0,
            )
        elif self.binMethod == "optimized":
            try:
                khbins_centers = np.loadtxt("khbins_binCenters.dat")
                self.kh_clusters = clustering.AssignCenters(
                    khbins_centers[:, np.newaxis],
                    metric="euclidean",
                    stride=1,
                    n_jobs=None,
                    skip=0,
                )
            except:
                sys.stdout.write(
                    "khbins (khbins_binCenters.dat) not found: initializing\n"
                )
                self.get_initial_khbins_equalAlloc()
                self.kh_clusters = clustering.AssignCenters(
                    khbins_centers[:, np.newaxis],
                    metric="euclidean",
                    stride=1,
                    n_jobs=None,
                    skip=0,
                )
            if not hasattr(self, "kh_clusters"):
                sys.stdout.write("giving up: log uniform kh bins")
                self.get_initial_khbins()
            khbins_centers = self.kh_clusters.clustercenters[:, 0]
        dtraj_kh_clusters = self.kh_clusters.assign(self.khList)
        varh_iter = self.varh[dtraj_iter]
        alloc = np.zeros(
            nB
        )  # get bin objective function, value and allocation over set of bins
        bin_kh_var = np.zeros(nB)
        for i in range(nB):
            indBin = np.where(dtraj_kh_clusters == i)
            if indBin[0].size == 0:
                alloc[i] = 0.0
                bin_kh_var[i] = 0.0
            else:
                n = indBin[0].size
                bin_kh_var[i] = np.var(self.khList[indBin])
                wt = np.sum(self.weightList[indBin])
                vw = np.sum(np.multiply(self.weightList[indBin], varh_iter[indBin]))
                alloc[i] = (wt * vw) ** 0.5
        if self.allocationMethod == "uniform":
            alloc = np.ones_like(alloc)
        alloc = alloc / np.sum(alloc)
        self.alloc = alloc
        base_walkers = self.min_walkers * np.ones_like(alloc)
        nBase = np.sum(base_walkers)
        if hasattr(self, "nAdapt"):
            nAdapt = self.nAdapt
        else:
            nAdapt = self.nW - nBase
        if nAdapt < 0:
            nAdapt = 0
        walkers = np.round(alloc * nAdapt)
        walkers = walkers + base_walkers
        indZero = np.where(walkers == 0.0)
        walkers[indZero] = 1.0
        walkers = walkers.astype(int)
        khbins_centers = self.kh_clusters.clustercenters[:, 0]
        khbins_centers_unique, ind_unique = np.unique(khbins_centers, return_index=True)
        walkers = walkers[ind_unique]
        bin_kh_var = bin_kh_var[ind_unique]
        binEdges = np.zeros(khbins_centers_unique.size + 1)
        binEdges[0] = -np.inf
        binEdges[-1] = np.inf
        # ind=np.argsort(khbins_centers_unique) #note sorting makes kh_clusters indexes different
        self.khbins_binCenters = khbins_centers_unique  # [ind]
        binEdges[1:-1] = 0.5 * (
            self.khbins_binCenters[1:] + self.khbins_binCenters[0:-1]
        )
        self.khbins_binEdges = binEdges
        self.walkers_per_bin = walkers  # [ind]
        self.bin_kh_var = bin_kh_var  # [ind]
        self.binObjective = np.sum(bin_kh_var)

    def write_iter_kh_pcoord(self):  # grab coordinates from WE traj_segs folder
        nS = self.nSeg
        if not hasattr(self, "model_clusters"):
            self.get_model_clusters()
        self.get_iter_coordinates()  # post coordinates
        dtraj_iter = self.model_clusters.assign(self.reduceCoordinates(self.coordList))
        kh_iter = self.kh[dtraj_iter]
        khList1 = np.array(kh_iter[:, 0])  # post pcoord
        self.get_iter_coordinates0()  # pre coordinates
        dtraj_iter = self.model_clusters.assign(self.reduceCoordinates(self.coordList))
        kh_iter = self.kh[dtraj_iter]
        khList0 = np.array(kh_iter[:, 0])  # pre pcoord
        westFile = self.fileList[self.westList[0]]
        dataIn = h5py.File(westFile, "a")
        pcoords = np.zeros(
            (0, 2, 2)
        )  # this is explicitly set up for p1 (target,basis def) and p2 (kh-aristoffian)
        for iS in range(self.nSeg):
            westFile = self.fileList[self.westList[iS]]
            pcoord = np.zeros((1, 2, 2))
            pcoord[0, 0, 0] = self.pcoord0List[iS, 0]
            pcoord[0, 1, 0] = self.pcoord1List[iS, 0]
            pcoord[0, 0, 1] = khList0[iS, 0]
            pcoord[0, 1, 1] = khList1[iS, 0]
            pcoords = np.append(pcoords, pcoord, axis=0)
            try:
                if iS > 0:
                    if self.westList[iS] != self.westList[iS - 1] and iS < nS - 1:
                        dsetName = "/iterations/iter_%08d/pcoord" % int(self.n_iter)
                        del dataIn[dsetName]
                        dset = dataIn.create_dataset(
                            dsetName, np.shape(pcoords[:-1, :, :])
                        )
                        dset[:] = pcoords[:-1, :, :]
                        dataIn.close()
                        pcoords = np.zeros(
                            (0, 2, 2)
                        )  # this is explicitly set up for p1 (target,basis def) and p2 (kh-aristoffian)
                        pcoords = np.append(pcoords, pcoord, axis=0)
                        dataIn = h5py.File(westFile, "a")
                    elif iS == nS - 1:
                        dsetName = "/iterations/iter_%08d/pcoord" % int(self.n_iter)
                        del dataIn[dsetName]
                        dset = dataIn.create_dataset(dsetName, np.shape(pcoords))
                        dset[:] = pcoords
                        sys.stdout.write(
                            "pcoords for iteration "
                            + str(self.n_iter)
                            + " overwritten\n"
                        )
                        dataIn.close()
            except:
                sys.stdout.write(
                    "error overwriting pcoord from "
                    + westFile
                    + " , iter "
                    + str(self.n_iter)
                    + " segment "
                    + str(self.segindList[iS])
                    + "\n"
                )

    def get_committor(self, conv):
        Mt = self.fluxMatrix.copy()
        nR = np.shape(Mt)
        sM = np.sum(Mt, 1)
        for iR in range(nR[0]):
            if sM[iR] > 0:
                Mt[iR, :] = Mt[iR, :] / sM[iR]
            if sM[iR] == 0.0:
                Mt[iR, iR] = 1.0
        sinkBins = self.indBasis  # np.where(avBinPnoColor==0.0)
        nsB = np.shape(sinkBins)
        nsB = nsB[0]
        for ii in sinkBins:
            Mt[ii, :] = np.zeros((1, self.nBins))
            Mt[ii, ii] = 1.0
        q = np.zeros((self.nBins, 1))
        q[self.indTargets, 0] = 1.0
        dconv = 100.0
        qp = np.ones_like(q)
        while dconv > conv:
            q[self.indTargets, 0] = 1.0
            q[self.indBasis, 0] = 0.0
            q = np.matmul(Mt, q)
            dconv = np.sum(np.abs(qp - q))
            sys.stdout.write("convergence: " + str(dconv) + "\n")
            qp = q.copy()
            self.q = q
        self.q = q

    def get_backwards_committor(self, conv):
        Mt = self.fluxMatrix.copy()
        nR = np.shape(Mt)
        sM = np.sum(Mt, 1)
        for iR in range(nR[0]):
            if sM[iR] > 0:
                Mt[iR, :] = Mt[iR, :] / sM[iR]
            if sM[iR] == 0.0:
                Mt[iR, iR] = 1.0
        sinkBins = self.indTargets  # np.where(avBinPnoColor==0.0)
        nsB = np.shape(sinkBins)
        nsB = nsB[0]
        for ii in sinkBins:
            Mt[ii, :] = np.zeros((1, self.nBins))
            Mt[ii, ii] = 1.0
        Mt = np.transpose(Mt)  # time reversal
        q = np.zeros((self.nBins, 1))
        q[self.indBasis, 0] = 1.0
        dconv = 100.0
        qp = np.ones_like(q)
        while dconv > conv:
            q[self.indBasis, 0] = 1.0
            q[self.indTargets, 0] = 0.0
            q = np.matmul(Mt, q)
            dconv = np.sum(np.abs(qp - q))
            sys.stdout.write("convergence: " + str(dconv) + "\n")
            qp = q.copy()
            self.qm = q
        self.q = q.copy()

    def plot_committor(self):
        fig = plt.figure(figsize=(8, 6))
        plt.scatter(self.binCenters, self.q, s=15, c="black")
        plt.yscale("log")
        plt.ylabel("Folding Committor", fontsize=12)
        plt.xlabel("Average microstate RMSD ($\AA$)", fontsize=12)
        plt.pause(1)
        fig.savefig(
            self.modelName
            + "_s"
            + str(self.first_iter)
            + "_e"
            + str(self.last_iter)
            + "committor.png"
        )
