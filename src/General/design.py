from rocketcea.cea_obj import CEA_Obj
from ambiance import Atmosphere

from General.units import Q_, unitReg
from General.units import R_UNIVERSAL
from fluids.gas import Gas

# eninge inputs

# props
oxName = "LOX"
fuelName = "RP-1"
OFratio = 2

# geometry
chamberPressure = Q_(300, unitReg.psi)
totalmdot = Q_(7.5, unitReg.pound / unitReg.sec)
chamberInternalRadius = Q_(3.825, unitReg.inch)
wallThickness = Q_(0.125, unitReg.inch)
maxRadius = chamberInternalRadius + wallThickness
plugBaseRadius = Q_(2, unitReg.inch)

# injector inputs
Spacing = Q_(0.55, unitReg.inch)  #Spacing between centear of impingement Holes
oxHoleRadius = Q_(2, unitReg.inch)  #Radial distance between centerline and LOX hole
percentFilmCooling = 0.15 #Outer Film Cooling Percentage
filmCoolingSpacing = Q_(0.60, unitReg.inch) #inches Outer
oxDoubletDiameter = Q_(0.0625, unitReg.inch)  #Design choise for DOublet Diameter size (Need to look more properly into it as 1/4 holes might make vaporization time too long)\
oxImpingeAngle = Q_(25, unitReg.degrees)
filmImpingeAngle = Q_(25, unitReg.degrees)
oxDewarPressure = Q_(22, unitReg.psi)
prescottAmbientTemp = Q_(70, unitReg.degF)
prescottAmbientPressure = Q_(12.2, unitReg.force_pound / unitReg.inch**2)

# Nozzle inputs
designAltitude = Q_(20000, unitReg.feet)
designAtm = Atmosphere(designAltitude.to(unitReg.meter).magnitude)

designAmbientPressure = Q_(designAtm.pressure[0], unitReg.pascal)
lengthMax = Q_(1.75, unitReg.inch)
basePressure = Q_(5, unitReg.psi)

# chamber derived
Combustion=CEA_Obj(oxName=oxName, fuelName=fuelName);
chamberTemp = Q_(Combustion.get_Tcomb(Pc=chamberPressure.magnitude, MR=OFratio), unitReg.degR)

# throat derived
_, _, _, molarWeightThroat, gamma = Combustion.get_IvacCstrTc_ThtMwGam(Pc=chamberPressure.magnitude, MR=OFratio, eps=1)
molarWeightThroat = Q_(molarWeightThroat, unitReg.pound / unitReg.lbmol)
R_throat = (R_UNIVERSAL / molarWeightThroat).to(unitReg.foot * unitReg.pound_force / (unitReg.pound * unitReg.degR))

# exhaust derived
exhaustGas = Gas(gamma, R_throat, P0=chamberPressure, T0=chamberTemp)
chokeArea = exhaustGas.getChokedArea(totalmdot).to(unitReg.inch**2)

# nozzle design table
plugDesignTable = {"throatArcRadFactor": .1, "convergeAngle": 25, "turnArcRadFactor": 2, "straightAngle": 10, "lipAngle":15, "manifoldDistanceFactor": .1}
# plugDesignTable = {"throatArcRadFactor": .1, "convergeAngle": 45, "turnArcRadFactor": 1.75, "straightAngle": 10, "lipAngle":15, "manifoldDistanceFactor": .1}