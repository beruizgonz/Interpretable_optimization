import pulp
import os 
import gurobipy as gp

real_data = os.path.join(os.getcwd(), "real_data")
problem1 = os.path.join(real_data, "openTEPES_9n_2030_sc01_st1.lp")
problem2 = os.path.join(real_data, "openTEPES_EAPP_2030_sc01_st1.lp")
output_file1 = os.path.join(real_data, "openTEPES_9n_2030_sc01_st1.mps")
output_file2 = os.path.join(real_data, "openTEPES_EAPP_2030_sc01_st1.mps")

#Load the LP problem from a file
# with open(problem2, "r") as file:
#     lp_problem = pulp.LpProblem.from_lp_string(file.read())
# # Write the problem to an MPS file
# lp_problem.writeMPS(output_file2)

#Write the problem to an MPS file

from gurobipy import read
# # Load the LP problem from a file
#lp_problem = pulp.LpProblem()
#lp_problem.readLP(problem2)

# model = read(problem2)
# # Write the model to an MPS file
# model.write(output_file2)


print("Conversion completed! The MPS file has been saved as 'output_file.mps'")
# Read the MPS file

gurobi_model = gp.read(output_file2)
# optimize the model
gurobi_model.optimize()
# Print the optimal objective value
print(f"Optimal objective value: {gurobi_model.objVal}")