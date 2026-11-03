model ElectricEIRAlignment
  package Medium = Buildings.Media.Water;
  parameter Boolean steady = false;
  parameter Buildings.Fluid.Chillers.Data.ElectricEIR.ElectricEIRChiller_McQuay_WSC_471kW_5_89COP_Vanes per;
  Buildings.Fluid.Chillers.ElectricEIR chi(
    redeclare package Medium1 = Medium,
    redeclare package Medium2 = Medium,
    per=per,
    energyDynamics=if steady then Modelica.Fluid.Types.Dynamics.SteadyState else Modelica.Fluid.Types.Dynamics.FixedInitial,
    T1_start=298.15, T2_start=278.15, tau1=30, tau2=30,
    dp1_nominal=0, dp2_nominal=0);
  Buildings.Fluid.Sources.MassFlowSource_T eva(
    redeclare package Medium = Medium, nPorts=1,
    m_flow=10.35, T=273.15+13.89);
  Buildings.Fluid.Sources.MassFlowSource_T con(
    redeclare package Medium = Medium, nPorts=1,
    m_flow=19.24, use_T_in=true);
  Buildings.Fluid.Sources.Boundary_pT sinkEva(redeclare package Medium=Medium,nPorts=1,p=300000);
  Buildings.Fluid.Sources.Boundary_pT sinkCon(redeclare package Medium=Medium,nPorts=1,p=300000);
equation
  connect(eva.ports[1], chi.port_a2);
  connect(chi.port_b2, sinkEva.ports[1]);
  connect(con.ports[1], chi.port_a1);
  connect(chi.port_b1, sinkCon.ports[1]);
  chi.on = time < 180 or time >= 300;
  chi.TSet = 273.15 + (if time < 360 then 8.89 else if time < 420 then 13.5 else 2);
  con.T_in = 273.15 + (if time < 480 then 26.67 else 25);
  annotation(experiment(StopTime=600,Interval=60,Tolerance=1e-8));
end ElectricEIRAlignment;

model ElectricEIRAlignmentSteady
  extends ElectricEIRAlignment(steady=true);
end ElectricEIRAlignmentSteady;
