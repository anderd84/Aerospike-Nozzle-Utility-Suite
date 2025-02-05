import matplotlib.pyplot as plt
import joblib
import multiprocessing as mp
from alive_progress import alive_bar, alive_it

from cooling.domain_mmap import DomainMMAP
from cooling import material, calc_cell
from general.units import Q_
from nozzle import plots
import numpy as np

def AnalyzeMC(domain: DomainMMAP, MAX_CORES: int = mp.cpu_count() - 1, tol: float = 1e-2, convPlot: bool = True):
    calcPoints = set()
    blacklist = set()
    # plt.ion()

    # fig = plots.CreateNonDimPlot()
    # imobj = domain.NodePlot(fig, "temperature", [material.DomainMaterial.CHAMBER, material.DomainMaterial.FREE])
    # fig.canvas.draw()
    # plt.pause(0.01)

    with alive_bar(domain.vpoints*domain.hpoints, title="Finding calculation points") as bar:
        for row in range(domain.vpoints):
            for col in range(domain.hpoints):
                if domain.material[row, col] not in material.MaterialType.STATIC_TEMP:
                    calcPoints.add((row, col))
                if domain.material[row, col] == material.DomainMaterial.COOLANT_BULK and domain.border[row, col]:
                    blacklist.add(tuple(domain.previousFlow[row, col]))
                bar()
    
    for pair in blacklist:
        calcPoints.remove(pair)

    if convPlot:
        plt.ion()
        convergePlot, ax = plt.subplots()
        ax.set_title("Convergence")
        ax.set_xlabel("Iteration")
        ax.set_ylabel("Max % Difference")
        ax.grid(True)

    diffArr = []

    with joblib.Parallel(n_jobs=MAX_CORES, return_as='generator') as parallel:
        diff = tol + 1
        numRows = domain.vpoints
        i = 0
        while diff > tol:
            i += 1
            diff = 0
            maxT = 0
            changes = []
            with alive_bar(len(calcPoints), title=f"Analyzing iteration {i}") as bar:
                outputs = parallel(
                    joblib.delayed(calc_cell.CalculateCell)(domain, row, col) for row, col in calcPoints
                )
                for output in outputs:
                    for changeOrder in output:
                        changes.append(changeOrder)
                        row, col = changeOrder.row, changeOrder.col
                        if changeOrder.temperature is not None:
                            newTemp = changeOrder.temperature
                            newDiff = abs(domain.temperature[row, col].magnitude - newTemp.to(domain.units["temperature"]).magnitude) / domain.temperature[row, col].magnitude
                            diff = max(diff, newDiff)
                            maxT = max(maxT, newTemp.magnitude)
                            # if newTemp.m > 1e4 or newTemp.m < 0:
                            #     print(f"Temp out of bounds: {newTemp}")
                            #     print(f"Row: {row}, Col: {col}")
                            #     print(f"material: {domain.material[row, col]}")
                            #     print(f"border: {domain.border[row, col]}")

                    bar()

            for changeOrder in alive_it(changes):
                row, col = changeOrder.row, changeOrder.col
                if changeOrder.temperature is not None:
                    currentTemp = domain.temperature[row, col]
                    newTemp = changeOrder.temperature
                    diff_ = newTemp.m - currentTemp.m
                    # maxChange = currentTemp.m / 100
                    maxChange = np.sign(diff_)
                    if False and (domain.material[row, col] in material.MaterialType.COOLANT or domain.border[row,col]):
                        domain.setMEM(row, col, 'temperature', Q_(max(min(abs(diff_), maxChange), -abs(diff_)),currentTemp.units) + currentTemp)
                        if abs(diff_) > 100:
                            domain.setMem(row, col, temperature, currentTemp - diff)
                    else:
                        domain.setMEM(row, col, 'temperature', changeOrder.temperature)
                if changeOrder.pressure is not None:
                    domain.setMEM(row, col, 'pressure', changeOrder.pressure)

            print(f"Max diff: {diff*100}%")
            print(f"Max temp: {maxT}R")
            diffArr.append(diff*100)

            # imobj = domain.updateNodePlot(imobj, "temperature", [material.DomainMaterial.CHAMBER, material.DomainMaterial.FREE])
            # fig.canvas.draw()
            # fig.canvas.flush_events()
            # plt.pause(0.01)

            if convPlot:
                # del convergeP
                ax.clear()
                ax.grid(True)
                iarr = max(0, i - 15)
                ax.plot(range(iarr, i), diffArr[iarr:], 'k-')
                # convergeP = ax.plot(range(i), diffArr, 'r-')
                ax.autoscale(axis='y')
                
                convergePlot.canvas.draw()
                convergePlot.canvas.flush_events()

            if i % 5 == 0:
                print("saving progress")
                mesh = domain.toDomain()
                mesh.DumpFile("save")
        
            # if maxT > 1000:
            #     print("max temp too high, stopping")
            #     mesh = domain.toDomain()
            #     mesh.DumpFile("save")
            #     break