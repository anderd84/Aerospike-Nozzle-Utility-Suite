from dataclasses import dataclass
from enum import Enum
import os
import random
import shutil
import string
import tempfile
import time
from fluids.gas import Gas
import numpy as np
import pint
np.product = np.prod
import matplotlib.pyplot as plt
import matrix_viewer as mv
from scipy.optimize import fsolve
from typing import Any

import multiprocessing as mp
from multiprocessing import Queue
import joblib
from alive_progress import alive_bar, alive_it
import gc

from icecream import ic

from Cooling.material import DomainMaterial
from Cooling import material
from Nozzle import plots
from General.units import Q_, unitReg
from fluids import gas

mcQ = Queue()
SHAREDMEMNAME = 'CoolingDomain'

@dataclass
class CoolingChannel:
    upperContour: np.ndarray
    lowerContour: np.ndarray    

@dataclass
class DomainPoint:
    x: float
    r: float
    area: float
    material: DomainMaterial = DomainMaterial.FREE
    border: bool = False
    temperature: Q_ = Q_(70, unitReg.degF)
    pressure: Q_ = Q_(12.1, unitReg.psi)
    velocity: Q_ = Q_(0, unitReg.ft/unitReg.s)
    hydraulicDiameter: Q_ = Q_(0, unitReg.inch)
    previousFlow: tuple[int, int] = (0,0)
    flowHeight: Q_ = Q_(0, unitReg.inch)

class DomainMC:
    array: np.ndarray
    x0: float
    r0: float
    width: float
    height: float
    xstep: float
    rstep: float
    hpoints: int
    vpoints: int

    def __init__(self, x0, r0, width, height, ds = .1):        
        hpoints = int(width/ds) + 1
        vpoints = int(height/ds) + 1
        
        self.array = np.empty((vpoints, hpoints), dtype=DomainPoint)

        self.x0 = x0
        self.r0 = r0
        self.width = width
        self.height = height
        self.hpoints = hpoints
        self.vpoints = vpoints
        self.xstep = width/(hpoints-1)
        self.rstep = height/(vpoints-1)
        print("Creating domain")
        with alive_bar(vpoints*hpoints) as bar:
            for i in range(vpoints):
                for j in range(hpoints):
                    self.array[i,j] = DomainPoint(x0 + j*self.xstep, r0 - i*self.rstep, self.xstep*self.rstep)
                    bar()
        print("Domain created")

    def DefineMaterials(self, cowl: np.ndarray, coolant: np.ndarray, chamber: np.ndarray, plug: np.ndarray, max_cores = mp.cpu_count() - 1):
        MAX_CORES = max_cores
        print(f"using {MAX_CORES} cores")
        tic = time.perf_counter()

        print("Starting processes")
        with joblib.Parallel(n_jobs=MAX_CORES, verbose=100, return_as='generator') as parallel:

            with alive_bar(self.vpoints*self.hpoints) as bar:
                print("Starting processes")

                outputs = parallel(joblib.delayed(EvalMaterialProcess2)(i, self.hpoints, i, (self.x0, self.xstep, self.r0, self.rstep), (self.width, self.height), cowl, chamber, plug) for i in range(self.vpoints))
                print(outputs)

                print("Assinging outputs")
                for out in outputs:
                    for i, j, mat in out:
                        self.array[i,j].material = mat
                        bar()
            
            try:
                shutil.rmtree('./.work')
            except OSError as e:
                print("Error: %s - %s." % (e.filename, e.strerror))

        print("Parallel computation done")
        print("assigning borders")
        self.AssignBorders()
        toc = time.perf_counter()
        print("material defined")
        print(f"Time to define materials: {toc - tic}")

    def ShowMaterialPlot(self, fig: plt.Figure):
        xarr = np.array([[point.x for point in row] for row in self.array])
        rarr = np.array([[point.r for point in row] for row in self.array])
        matarr = np.array([[(point.material.value) for point in row] for row in self.array])

        # extent = [xarr[0,0]-self.xstep, xarr[-1,-1]+self.xstep, rarr[-1,-1]-self.rstep, rarr[0,0]+self.rstep]
        extent = [xarr[0,0]-self.xstep/2, xarr[-1,-1]+self.xstep/2, rarr[-1,-1]-self.rstep/2, rarr[0,0]+self.rstep/2]
        ax = fig.axes[0]
        # contf = ax.contourf(xarr, rarr, matarr, levels=[0, 1, 4] , colors=['white', 'blue', 'red'])
        # contf = ax.contourf(xarr, rarr, matarr)
        ax.imshow(matarr, extent=extent, origin='upper', cmap='jet')
        xcells = np.linspace(self.x0 - self.xstep/2, self.x0 + self.width + self.xstep/2, self.hpoints+1)
        rcells = np.linspace(self.r0 + self.rstep/2, self.r0 - self.height - self.rstep/2, self.vpoints+1)
        xl, rl = np.meshgrid(xcells, rcells)
        # ax.plot(xl, rl, 'k', linewidth=0.25)
        # ax.plot(np.transpose(xl), np.transpose(rl), 'k', linewidth=0.25)  
          
        # for i in range(self.vpoints):
        #     for j in range(self.hpoints):
        #         flow = self.array[i,j].previousFlow
        #         if flow[0] != 0:
        #             if self.array[i,j].material == DomainMaterial.COOLANT_WALL:
        #                 ax.plot([self.array[i,j].x, self.array[flow].x], [self.array[i,j].r, self.array[flow].r], '-b', linewidth=1)
        #             else:
        #                 ax.plot([self.array[i,j].x, self.array[flow].x], [self.array[i,j].r, self.array[flow].r], '-k', linewidth=1)        

    def ShowStatePlot(self, fig: plt.Figure):
        print("state plot!")
        xarr = np.array([[point.x for point in row] for row in self.array])
        print("xarr done!")
        rarr = np.array([[point.r for point in row] for row in self.array])
        print("rarr done!")
        
        matarr = np.array([[point.temperature.to(unitReg.degR).magnitude for point in row] for row in self.array])
        print("matarr done!")

        ax = fig.axes[0]
        contf = ax.contourf(xarr, rarr, matarr, 100, cmap='jet')
        fig.colorbar(contf, ax=ax)
        # xcells = np.linspace(self.x0 - self.xstep/2, self.x0 + self.width + self.xstep/2, self.hpoints+1)
        # rcells = np.linspace(self.r0 + self.rstep/2, self.r0 - self.height - self.rstep/2, self.vpoints+1)
        # xl, rl = np.meshgrid(xcells, rcells)
        print("done!")
        # ax.plot(xl, rl, 'k', linewidth=0.25)
        # ax.plot(np.transpose(xl), np.transpose(rl), 'k', linewidth=0.25)

    def ShowBorderPlot(self, fig: plt.Figure):
        xarr = np.array([[point.x for point in row] for row in self.array])
        rarr = np.array([[point.r for point in row] for row in self.array])
        matarr = np.array([[int(point.border) for point in row] for row in self.array])

        # extent = [xarr[0,0]-self.xstep, xarr[-1,-1]+self.xstep, rarr[-1,-1]-self.rstep, rarr[0,0]+self.rstep]
        extent = [xarr[0,0]-self.xstep/2, xarr[-1,-1]+self.xstep/2, rarr[-1,-1]-self.rstep/2, rarr[0,0]+self.rstep/2]
        ax = fig.axes[0]
        # contf = ax.contourf(xarr, rarr, matarr, levels=[0, 1, 4] , colors=['white', 'blue', 'red'])
        # contf = ax.contourf(xarr, rarr, matarr)
        ax.imshow(matarr, extent=extent, origin='upper', cmap='jet')
        xcells = np.linspace(self.x0 - self.xstep/2, self.x0 + self.width + self.xstep/2, self.hpoints+1)
        rcells = np.linspace(self.r0 + self.rstep/2, self.r0 - self.height - self.rstep/2, self.vpoints+1)
        xl, rl = np.meshgrid(xcells, rcells)
        # ax.plot(xl, rl, 'k', linewidth=0.25)
        # ax.plot(np.transpose(xl), np.transpose(rl), 'k', linewidth=0.25)

    def AssignCoolantFlow(self, coolant: CoolingChannel, upperWall: bool, initialPressure: Q_):
        inputPoints = len(coolant.upperContour)
        previousWall = (0,0)
        previousFlow = (0,0)
        with alive_bar(inputPoints - 1) as bar:
            for i in range(inputPoints - 1):
                dist1 = np.sqrt((coolant.lowerContour[i].x - coolant.lowerContour[i+1].x)**2 + (coolant.lowerContour[i].r - coolant.lowerContour[i+1].r)**2)
                dist2 = np.sqrt((coolant.upperContour[i].x - coolant.upperContour[i+1].x)**2 + (coolant.upperContour[i].r - coolant.upperContour[i+1].r)**2)
                dist = max(dist1, dist2)

                step = min(self.xstep, self.rstep)
                steps = max(int(dist/step * 1.5), 5)

                xl = np.linspace(coolant.lowerContour[i].x, coolant.lowerContour[i+1].x, steps)[:-1]
                rl = np.linspace(coolant.lowerContour[i].r, coolant.lowerContour[i+1].r, steps)[:-1]

                xu = np.linspace(coolant.upperContour[i].x, coolant.upperContour[i+1].x, steps)[:-1]
                ru = np.linspace(coolant.upperContour[i].r, coolant.upperContour[i+1].r, steps)[:-1]

                for j in range(steps - 1):
                    wallPoint = self.CoordsToCell(xu[j], ru[j]) if upperWall else self.CoordsToCell(xl[j], rl[j])
                    cells = self.cellsOnLine((xl[j], rl[j]), (xu[j], ru[j]))

                    if xl[j] > self.x0 + self.width or xu[j] > self.x0 + self.width:
                        break
                    if xl[j] < self.x0 or xu[j] < self.x0:
                        break

                    if rl[j] < self.r0 - self.height or ru[j] < self.r0 - self.height:
                        break
                    if rl[j] > self.r0 or ru[j] > self.r0:
                        break

                    # plt.plot([xl[j], xu[j]], [rl[j], ru[j]], '-b', linewidth=.25)

                    for row, col in cells:
                        if (i==0 and j==0) or self.array[row, col].material == DomainMaterial.COOLANT_INLET:
                            self.array[row,col].material = DomainMaterial.COOLANT_INLET

                        if row == wallPoint[0] and col == wallPoint[1]:
                            if row != previousWall[0] or col != previousWall[1]:
                                previousFlow = previousWall
                            self.array[row, col].material = DomainMaterial.COOLANT_WALL if self.array[row, col].material != DomainMaterial.COOLANT_INLET else DomainMaterial.COOLANT_INLET
                            self.array[row, col].previousFlow = previousFlow
                            previousWall = (row, col)
                        else:
                            if self.array[row, col].material in [DomainMaterial.COOLANT_WALL, DomainMaterial.COOLANT_INLET, DomainMaterial.COOLANT_BULK]:
                                continue
                            self.array[row, col].material = DomainMaterial.COOLANT_BULK
                            self.array[row, col].previousFlow = wallPoint
                        
                        self.array[row, col].pressure = initialPressure
                        self.array[row, col].flowHeight = Q_(np.sqrt((xl[j] - xu[j])**2 + (rl[j] - ru[j])**2), unitReg.inch)
                bar()
                
        print("done")

        print("assigning borders")
        self.AssignBorders()
        print("done")

    def AssignChamberTemps(self, chamber: np.ndarray, exhaust: Gas, startPoint: tuple, endPoint: tuple, chamberWallRadius: Q_, plugBase: Q_, Astar: Q_, fig):
        tic = time.perf_counter()
        print("assigning stagnant")
        flowAngle = np.arctan((endPoint[1] - startPoint[1])/(endPoint[0] - startPoint[0]))
        phi = np.pi/2 - flowAngle

        farAway1 = (startPoint[0] - chamberWallRadius.magnitude*np.sin(flowAngle), startPoint[1] + chamberWallRadius.magnitude*np.cos(flowAngle))
        farAway2 = (startPoint[0] + chamberWallRadius.magnitude*np.sin(flowAngle), startPoint[1] - chamberWallRadius.magnitude*np.cos(flowAngle))
        startPointU, _ = material.intersectPolyAt(chamber, startPoint, farAway1)
        startPointL, _ = material.intersectPolyAt(chamber, startPoint, farAway2)

        originX = np.linspace(startPoint[0], endPoint[0], int(self.hpoints))
        originR = np.linspace(startPoint[1], endPoint[1], int(self.hpoints))

        iStart, jStart = self.ChamberStartCell()

        for j in range(jStart, self.hpoints):
            for i in range(iStart, self.vpoints):
                if self.array[i,j].material != DomainMaterial.CHAMBER:
                    break
                if self.lineInCell(startPointU, startPointL, i, j):
                    jStart = j if i == iStart else jStart
                    continue
                self.array[i,j].temperature = exhaust.stagTemp
                self.array[i,j].velocity = Q_(1, unitReg.foot/unitReg.sec)
                self.array[i,j].hydraulicDiameter = 2*(chamberWallRadius - plugBase)
            if self.lineInCell(startPointU, startPointL, i, j):
                break

        with alive_bar(originX.size) as bar:
            print(f"Assinging straight flow")
            for oX, oR in zip(originX, originR):
                farAway1 = (oX - chamberWallRadius.magnitude*np.sin(flowAngle), oR + chamberWallRadius.magnitude*np.cos(flowAngle))
                farAway2 = (oX + chamberWallRadius.magnitude*np.sin(flowAngle), oR - chamberWallRadius.magnitude*np.cos(flowAngle))
                startPointU, _ = material.intersectPolyAt(chamber, (oX, oR), farAway1)
                startPointL, _ = material.intersectPolyAt(chamber, (oX, oR), farAway2)

                # plt.plot([startPointU[0], startPointL[0]], [startPointU[1], startPointL[1]], '-gx')

                area = np.pi/np.sin(phi) * (startPointU[1]**2 - startPointL[1]**2)

                AAstar = Q_(area, unitReg.inch**2)/Astar
                mach = fsolve(lambda M: gas.Isentropic1DExpansion(M, exhaust.gammaTyp) - AAstar, .25)[0]
                temperature = (gas.StagTempRatio(mach, exhaust) * exhaust.stagTemp)
                velocity = mach * np.sqrt(exhaust.getVariableGamma(mach) * exhaust.Rgas * temperature)
                hydroD = Q_(2*np.sqrt((startPointU[0] - startPointL[0])**2 + (startPointU[1] - startPointL[1])**2), unitReg.inch)

                cells = self.cellsOnLine(startPointL, startPointU)
                for i,j in cells:
                    if self.array[i,j].material == DomainMaterial.CHAMBER:
                        self.array[i,j].temperature = temperature
                        self.array[i,j].velocity = velocity
                        self.array[i,j].hydraulicDiameter = hydroD
                bar()


        # curve section
        print(f"assigning bend flow")
        farAway = (endPoint[0] - chamberWallRadius.magnitude*np.sin(flowAngle), endPoint[1] - chamberWallRadius.magnitude*np.cos(flowAngle))
        plt.plot(farAway[0], farAway[1], 'rx')
        
        intersect, indexPair = material.intersectPolyAt(chamber, endPoint, farAway)
        distance = np.sqrt((chamber[indexPair[0]].x - chamber[indexPair[1]].x)**2 + (chamber[indexPair[0]].r - chamber[indexPair[1]].r)**2)
        interpFactor = int(np.ceil(5*distance / self.xstep))
        ic(interpFactor)
        plt.plot([intersect[0]], [intersect[1]], 'gx')

        iiContourStart = indexPair[0]

        curAngle = np.pi/2 + np.arctan2(chamber[iiContourStart+2].r - chamber[iiContourStart+1].r, chamber[iiContourStart+2].x - chamber[iiContourStart+1].x)
        prevAngle = np.pi/2 + np.arctan2(chamber[iiContourStart+1].r - chamber[iiContourStart].r, chamber[iiContourStart+1].x - chamber[iiContourStart].x)
        angle0 = prevAngle
        ii = iiContourStart + 1
        ii1 = ii + 1
        # cArr = ['.b-', '.k-', '.k-', '.k-', '.k-', '.k-', '.k-', '.k-', '.k-', '.k-', '.k-', '.k-']
        # ic(angle)
        while curAngle <= angle0 + 1e-3:
            # ci = 0
            angles = np.linspace(prevAngle, curAngle, interpFactor + 1)
            points = np.linspace((chamber[ii].x, chamber[ii].r), (chamber[ii+1].x, chamber[ii+1].r), interpFactor + 1)
            for angle, lowerPoint in zip(angles[:-1], points[:-1]):
                farAway = (lowerPoint[0] + chamberWallRadius.magnitude*np.cos(angle), lowerPoint[1] + chamberWallRadius.magnitude*np.sin(angle))
                upperPoint, _ = material.intersectPolyAt(chamber, (lowerPoint[0], lowerPoint[1] + 1e-3), farAway)

                # plt.plot([lowerPoint[0], upperPoint[0]], [lowerPoint[1], upperPoint[1]], cArr[ci % 10], linewidth=.5)
                # ci += 1

                area = np.pi/np.sin(angle) * (upperPoint[1]**2 - lowerPoint[1]**2)

                AAstar = Q_(area, unitReg.inch**2)/Astar
                if AAstar < 1:
                    mach = 1
                else:
                    mach = fsolve(lambda M: gas.Isentropic1DExpansion(M, exhaust.gammaTyp) - AAstar, .25)[0]
                temperature = (gas.StagTempRatio(mach, exhaust) * exhaust.stagTemp)
                velocity = mach * np.sqrt(exhaust.getVariableGamma(mach) * exhaust.Rgas * temperature)
                hydroD = Q_(2*np.sqrt((upperPoint[0] - lowerPoint[0])**2 + (upperPoint[1] - lowerPoint[1])**2), unitReg.inch)

                cells = self.cellsOnLine(lowerPoint, upperPoint)
                for i,j in cells:
                    if self.array[i,j].material == DomainMaterial.CHAMBER:
                        self.array[i,j].temperature = temperature
                        self.array[i,j].velocity = velocity
                        self.array[i,j].hydraulicDiameter = hydroD

            ii = ii1

            ii1 = ii + 1
            if ii1 >= len(chamber):
                ii1 = 0
            prevAngle = curAngle
            curAngle = np.pi/2 + np.arctan2(chamber[ii1].r - chamber[ii].r, chamber[ii1].x - chamber[ii].x)
        
        toc = time.perf_counter()
        print(f"Time to assign chamber temps: {toc - tic}")
        
    def AssignBorders(self):
        finalI = self.vpoints - 1
        finalJ = self.hpoints - 1

        with alive_bar(self.vpoints*self.hpoints) as bar:
            for i in range(self.vpoints):
                for j in range(self.hpoints):
                    lowI = max(i - 1, 0)
                    lowJ = max(j - 1, 0)
                    highI = min(i + 1, finalI)
                    highJ = min(j + 1, finalJ)
                    checks = [self.array[lowI, j].material, self.array[highI, j].material, self.array[i, lowJ].material, self.array[i, highJ].material]
                    self.array[i, j].border = not(checks[0] == checks[1] and checks[1] == checks[2] and checks[2] == checks[3])
                    bar()

    def cellsOnLine(self, point1, point2):
        linedx = point2[0] - point1[0]
        linedr = point2[1] - point1[1]
        cellsx = int(linedx / self.xstep)
        cellsr = int(linedr / self.rstep)

        cellsLine = max(int(np.sqrt(cellsx**2 + cellsr**2) * 1.5),10)
        x = np.linspace(point1[0], point2[0], cellsLine)
        r = np.linspace(point1[1], point2[1], cellsLine)

        return [self.CoordsToCell(xp, rp) for xp, rp in zip(x,r)]    

    def isInCell(self, point, row, col):
        xmin = self.array[row, col].x - self.xstep/2
        xmax = self.array[row, col].x + self.xstep/2
        ymin = self.array[row, col].r - self.rstep/2
        ymax = self.array[row, col].r + self.rstep/2
        return xmin <= point[0] and point[0] <= xmax and ymin <= point[1] and point[1] <= ymax
        
    def lineInCell(self, point1, point2, row, col, res = -1):
        m = (point2[1] - point1[1]) / (point2[0] - point1[0])
        a = -m
        b = 1
        c = m*point1[0] - point1[1]
        x0 = self.array[row, col].x
        y0 = self.array[row, col].r

        x = (b*(b*x0 - a*y0) - a*c)/(a**2 + b**2)
        y = (a*(-b*x0 + a*y0) - b*c)/(a**2 + b**2)
        return self.isInCell((x,y), row, col)
    
    def ChamberStartCell(self):
        for i in range(self.vpoints):
            for j in range(self.hpoints):
                if self.array[i,j].material == DomainMaterial.CHAMBER:
                    return (i, j)

    def CoordsToCell(self, x, r):
        dx = x - self.x0 + self.xstep/2
        dr = self.r0 - r + self.rstep/2
        i = int((dr/self.rstep))
        j = int((dx/self.xstep))
        return (i, j)

    def DumpFile(self, filename):
        joblib.dump(self, filename + '.z', compress=True)

    @staticmethod
    def LoadFile(filename):
        print("Loading file")
        loaded: DomainMC = joblib.load(filename + '.z')
        # DomainMC.ConvertUnits(loaded)
        return loaded
    
    @staticmethod
    def ConvertUnits(domain):
        print("Converting units")
        attributes = list(domain.array[0,0].__dict__.keys())
        for attr in attributes:
            testAttr = domain.array[0,0].__getattribute__(attr)
            if isinstance(testAttr, pint.Quantity):
                with alive_bar(domain.vpoints*domain.hpoints) as bar:
                    print(f"Converting {attr}")
                    unit = str(testAttr.units)
                    t = [[domain.array[i,j].__getattribute__(attr).magnitude for i in range(domain.vpoints)] for j in range(domain.hpoints)]
                    for i in range(domain.vpoints):
                        for j in range(domain.hpoints):
                            domain.array[i,j].__setattr__(attr, Q_(t[j][i], unit))
                            bar()
        return domain

class DomainMMAP(DomainMC):
    attributes: list = []
    memmaps: dict = {}

    units: dict = {}

    workingFolder = tempfile.mkdtemp()
    prefix = str(''.join(random.choices(string.ascii_letters, k=4)))

    def __init__(self, domain: DomainMC):
        self.x0 = domain.x0
        self.r0 = domain.r0
        self.width = domain.width
        self.height = domain.height
        self.hpoints = domain.hpoints
        self.vpoints = domain.vpoints
        self.xstep = domain.xstep
        self.rstep = domain.rstep

        print("Loading domain")
        self.attributes = list(DomainPoint(0, 0, 0).__dict__.keys())

        for attr in alive_it(self.attributes):
            print(f"Transferring {attr}")
            testAttr = domain.array[0,0].__getattribute__(attr)
            if isinstance(testAttr, pint.Quantity):
                self.units[attr] = str(testAttr.units)
                t = [[domain.array[i,j].__getattribute__(attr).to(testAttr.units).magnitude for j in range(domain.hpoints)] for i in range(domain.vpoints)]
            elif isinstance(testAttr, Enum):
                t = [[domain.array[i,j].__getattribute__(attr).value for j in range(domain.hpoints)] for i in range(domain.vpoints)]
            elif isinstance(testAttr, tuple):
                t = [[[a for a in domain.array[i,j].__getattribute__(attr)] for j in range(domain.hpoints)] for i in range(domain.vpoints)]
            else:
                t = [[domain.array[i,j].__getattribute__(attr) for j in range(domain.hpoints)] for i in range(domain.vpoints)]
            shape = (domain.vpoints, domain.hpoints) if not isinstance(testAttr, tuple) else (domain.vpoints, domain.hpoints, len(testAttr))
            self.memmaps[attr] = np.memmap(f'{self.workingFolder}/{self.prefix}_{attr}.dat', dtype='float64', mode='w+', shape=shape)
            self.memmaps[attr][:] = t[:]
            del t

    def __getattribute__(self, name: str) -> Any:
        try:
            return super().__getattribute__(name)
        except AttributeError:
            if name in self.attributes:
                if name in self.units:
                    return Q_(self.memmaps[name][:], self.units[name])
                return self.memmaps[name]
            else:
                return super().__getattribute__(name)
            
    def __setattr__(self, name: str, value: Any) -> None:
        if name in ['attributes', 'memmaps', 'units', 'workingFolder', 'prefix'] or name in super().__dir__():
            super().__setattr__(name, value)
        else:
            if name in self.attributes:
                if isinstance(value, pint.Quantity):
                    self.memmaps[name][:] = value.to(self.units[name]).magnitude
                elif isinstance(value, Enum):
                    self.memmaps[name][:] = value.value
                else:
                    self.memmaps[name][:] = value
                self.memmaps[name].flush()
            else:
                super().__setattr__(name, value)

    def toDomain(self):
        domain = DomainMC(self.x0, self.r0, self.width, self.height)
        for i in range(self.vpoints):
            for j in range(self.hpoints):
                for attr in self.attributes:
                    if attr in self.units:
                        domain.array[i,j].__setattr__(attr, Q_(self.memmaps[attr][i,j], self.units[attr]))
                    else:
                        domain.array[i,j].__setattr__(attr, self.memmaps[attr][i,j])
        return domain

def EvalMaterialProcess2(i, hsteps, pn, gridData, size, cowl, chamber, plug):
    res = []

    x0 = gridData[0]
    xstep = gridData[1]
    r0 = gridData[2]
    rstep = gridData[3]

    for j in range(hsteps):
        point = (x0 + j*xstep, r0 - i*rstep)
        material = AssignMaterial(point, size, np.array([]), cowl, chamber, plug)
        res.append((i, j, material))
    return res

def AssignMaterial(point, size, coolant, cowl, chamber, plug):
    if material.isIntersect(point, coolant, size):
        return DomainMaterial.COOLANT
    if material.isIntersect(point, cowl, size):
        return DomainMaterial.COWL
    if material.isIntersect(point, chamber, size):
        return DomainMaterial.CHAMBER
    if material.isIntersect(point, plug, size):
        return DomainMaterial.PLUG
    return DomainMaterial.FREE