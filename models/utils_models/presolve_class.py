import numpy as np
from scipy.sparse import csr_matrix
from Interpretable_Optimization.models.utils_models.utils_functions import get_model_matrices, \
    find_corresponding_negative_rows_with_indices, nested_dict, linear_dependency, normalize_features, \
    matrix_sparsification
from collections import defaultdict
import warnings


class PresolveComillas:
    def __init__(self,
                 model=None,
                 perform_eliminate_zero_rows=False,
                 perform_eliminate_zero_columns=False,
                 perform_eliminate_singleton_equalities=False,
                 perform_eliminate_kton_equalities=False,
                 k=5,
                 perform_eliminate_singleton_inequalities=False,
                 perform_eliminate_dual_singleton_inequalities=False,
                 perform_eliminate_redundant_columns=False,
                 perform_eliminate_implied_bounds=False,
                 perform_eliminate_redundant_rows=False,
                 perform_reduction_small_coefficients=False):
        """
        Initialize the presolve operations class with an optional optimization model.

        Parameters:
        - model: An optimization model (e.g., a Gurobi model object) that presolve operations will be applied to.
        Default is None.
        """
        self.model = model

        # input data for some operations
        self.k = k  # kton equalities

        # boolean for presolve reductions
        self.perform_eliminate_zero_rows = perform_eliminate_zero_rows
        self.perform_eliminate_zero_columns = perform_eliminate_zero_columns
        self.perform_eliminate_singleton_equalities = perform_eliminate_singleton_equalities
        self.perform_eliminate_kton_equalities = perform_eliminate_kton_equalities
        self.perform_eliminate_singleton_inequalities = perform_eliminate_singleton_inequalities
        self.perform_eliminate_dual_singleton_inequalities = perform_eliminate_dual_singleton_inequalities
        self.perform_eliminate_redundant_columns = perform_eliminate_redundant_columns
        self.perform_eliminate_implied_bounds = perform_eliminate_implied_bounds
        self.perform_eliminate_redundant_rows = perform_eliminate_redundant_rows
        self.perform_reduction_small_coefficients = perform_reduction_small_coefficients

        # Initialize placeholders for matrices and model components
        self.A = None
        self.b = None
        self.c = None
        self.co = None
        self.lb = None
        self.ub = None
        self.of_sense = None
        self.cons_senses = None
        self.variable_names = None
        self.original_row_index = None
        self.original_column_index = None

        # Initialize dictionary to track changes made by presolve operations
        self.change_dictionary = defaultdict(nested_dict)

        # Initialize table to track the number of variables and constraints at each operation
        self.operation_table = []

    def load_model_matrices(self):
        """
        Extract and load matrices and other components from the optimization model.
        """
        if self.model is None:
            raise ValueError("Model is not provided.")

        self.A, self.b, self.c, self.co, self.lb, self.ub, self.of_sense, self.cons_senses, self.variable_names = (
            get_model_matrices(self.model))

        # Generate original row indices from 0 to the number of constraints
        self.original_row_index = list(range(self.A.A.shape[0]))

        # Generate original columns indices from 0 to the number of variables
        self.original_column_index = list(range(self.A.A.shape[1]))

        # Add initial counts to the operation table
        self.operation_table.append(("Initial", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def orchestrator_presolve_operations(self):
        """
        Perform presolve operations based on the specified configurations.
        """
        # Ensure matrices are loaded
        self.load_model_matrices()

        if self.perform_reduction_small_coefficients:
            self.reduction_small_coefficients()

        if self.perform_eliminate_implied_bounds:
            self.eliminate_implied_bounds()

        if self.perform_eliminate_redundant_rows:
            self.eliminate_redundant_rows()

        if self.perform_eliminate_kton_equalities:
            self.eliminate_kton_equalities()

        if self.perform_eliminate_singleton_equalities:
            self.eliminate_singleton_equalities()

        if self.perform_eliminate_singleton_inequalities:
            self.eliminate_singleton_inequalities()

        if self.perform_eliminate_dual_singleton_inequalities:
            self.eliminate_dual_singleton_inequalities()

        if self.perform_eliminate_redundant_columns:
            self.eliminate_redundant_columns()

        if self.perform_eliminate_zero_rows:
            self.eliminate_zero_rows()

        if self.perform_eliminate_zero_columns:
            self.eliminate_zero_columns()

        return (self.A, self.b, self.c, self.lb, self.ub, self.of_sense, self.cons_senses, self.co, self.variable_names,
                self.change_dictionary, self.operation_table)

    def get_row_activities(self):
        """
        Compute and return the support, minimal activity, and maximal activity for each row in a Gurobi model.
        Returns:
        support, min_activity, max_activity.
        SUPP - support: Set of indices j where a_ij is non-zero.
        INF - min_activity: Infimum of the row activity calculated as the sum of a_ij*l_j (for a_ij > 0) and a_ij*u_j (for a_ij < 0).
        SUP - max_activity: Supremum of the row activity calculated as the sum of a_ij*u_j (for a_ij > 0) and a_ij*l_j (for a_ij < 0).
        """

        # Initial values
        SUPP = []
        SUP = []
        INF = []

        num_rows, num_cols = self.A.A.shape

        for i in range(num_rows):
            support = set()
            min_activity = 0
            max_activity = 0

            for j in range(num_cols):
                a_ij = self.A.A[i, j]
                l_j = self.lb[j]
                u_j = self.ub[j]

                if a_ij != 0:
                    support.add(j)

                    if a_ij > 0:
                        min_activity += a_ij * l_j
                        max_activity += a_ij * u_j
                    else:
                        min_activity += a_ij * u_j
                        max_activity += a_ij * l_j

            SUPP.append(support)
            INF.append(min_activity)
            SUP.append(max_activity)

        return SUPP, INF, SUP

    def eliminate_zero_rows(self):
        """
        Eliminate zero rows from a Gurobi optimization model.

        This function first creates a copy of the given model. It then checks each
        constraint to identify zero rows, i.e., rows where all coefficients are zero.
        """
        to_delete = []
        num_rows, num_cols = self.A.A.shape
        to_delete_original = []

        for i in range(num_rows):
            row_values = self.A[i, :].toarray().flatten()  # Extract the i-th row as a dense array
            is_zero_row = np.all(row_values == 0)

            if is_zero_row:
                if self.b[i] <= 0:
                    to_delete.append(i)
                    to_delete_original.append(self.original_row_index[i])
                else:
                    # Emit a warning indicating that the model is infeasible
                    warnings.warn("Model is infeasible due to a non-redundant zero row with a positive RHS.",
                                  RuntimeWarning)

        # Removing rows from matrix A
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete, axis=0))

        # Removing elements from b, and constraint senses
        for index in sorted(to_delete, reverse=True):
            del self.b[index]
            del self.cons_senses[index]
            del self.original_row_index[index]

        # Update change_dictionary with the information about deleted elements
        self.change_dictionary['eliminate_zero_rows']['deleted_rows_indices'] = to_delete_original

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(("Eliminate Zero Rows", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_zero_columns(self):
        """
        This function identifies redundant or unbounded variables.
        It checks if a column in the coefficient matrix A is empty (all coefficients are zero).
        Depending on the cost coefficient c_j, the variable is classified as redundant, unbounded, or valid.
        """

        to_delete = []
        to_delete_original = []
        num_rows, num_cols = self.A.A.shape

        # Dictionary to store solutions for zero columns
        solution = {}

        for j in range(num_cols):
            # Extract the column corresponding to the variable
            col = self.A.A[:, j]

            # Check if all coefficients in the column are zero
            if all(c == 0 for c in col):
                c_j = self.c[j]

                # Classify based on c_j value
                if c_j >= 0:
                    to_delete.append(j)
                    to_delete_original.append(self.original_column_index[j])
                    # Update the solution dictionary
                    var_to_del = self.variable_names[j]
                    solution[var_to_del] = 0
                else:
                    # Emit a warning indicating that the model is unbounded
                    warnings.warn("Model is unbounded due to an empty column with a negative cost coefficient.",
                                  RuntimeWarning)

        # Removing columns from matrix A, corresponding elements from c, lb, ub, variables_names
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete, axis=1))
        # Iterating in reverse order to avoid index shifting issues
        for index in sorted(to_delete, reverse=True):
            del self.c[index]
            del self.variable_names[index]
            self.lb = np.delete(self.lb, index)
            self.ub = np.delete(self.ub, index)
            del self.original_column_index[index]

        # Update change_dictionary with the information about deleted elements
        self.change_dictionary['eliminate_zero_columns']['deleted_columns'] = to_delete_original
        self.change_dictionary['eliminate_zero_columns']['solution'] = solution

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(("Eliminate Zero Columns", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_singleton_equalities(self):
        """
        This function processes a Gurobi model to eliminate singleton equality constraints.
        It simplifies the model by fixing variables and updating the model accordingly.
        If a negative fixed value for a variable is found, the model is declared infeasible.
        """

        # Variable to track if we found a singleton in the current iteration
        found_singleton = True

        # Dictionary to store solutions for singletons
        solution = {}

        while found_singleton:
            found_singleton = False

            # Getting the number of nonzero elements per row
            nonzero_count_per_row = np.count_nonzero(self.A.A, axis=1)

            # Create a boolean array where True indicates rows with a single non-zero element
            single_nonzero = nonzero_count_per_row == 1

            has_negative_counterpart, indices_list = find_corresponding_negative_rows_with_indices(self.A, self.b)

            # Combine the two conditions -> single nonzero + negative counterpart
            valid_rows = np.logical_and(single_nonzero, has_negative_counterpart)

            # Find the index of the first row that satisfies both conditions
            first_singleton_index = np.where(valid_rows)[0][0] if np.any(valid_rows) else None

            # Check if the equality singleton row exists and process it
            if first_singleton_index is not None:

                found_singleton = True
                # Extract the singleton row
                singleton_row = self.A.A[first_singleton_index, :]

                # Identify the non-zero column (k)
                k_index = np.nonzero(singleton_row)[0][0]

                # Calculate the value for the variable corresponding to the singleton row
                x_k = self.b[first_singleton_index] / self.A.A[first_singleton_index, k_index]

                if x_k >= 0:

                    # identifying rows to delete
                    index_rows_to_delete = [first_singleton_index, indices_list[first_singleton_index]]
                    index_original_rows_to_delete = [self.original_row_index[first_singleton_index],
                                                     self.original_row_index[indices_list[first_singleton_index]]]
                    index_original_columns_to_delete = self.original_column_index[k_index]

                    # Update the solution dictionary
                    var_to_del = self.variable_names[k_index]
                    solution[var_to_del] = x_k

                    # update b
                    self.b = self.b - self.A.A[:, k_index] * x_k
                    self.b = self.b.tolist()

                    # Delete elements from b and the corresponding elements of the constraint operation
                    # Iterating in reverse order to avoid index shifting issues
                    for index in sorted(index_rows_to_delete, reverse=True):
                        del self.b[index]
                        del self.cons_senses[index]
                        del self.original_row_index[index]

                    # update objective function constant
                    if self.c[k_index] != 0:
                        self.co = self.co - self.c[k_index] * x_k

                    # Update A
                    self.A = csr_matrix(np.delete(self.A.toarray(), index_rows_to_delete, axis=0))
                    self.A = csr_matrix(np.delete(self.A.toarray(), k_index, axis=1))

                    # update c, lb, ub and cons_senses
                    del self.c[k_index]
                    self.lb = np.delete(self.lb, k_index)
                    self.ub = np.delete(self.ub, k_index)
                    del self.variable_names[k_index]
                    del self.original_column_index[k_index]

                    # Update change_dictionary with the information about deleted elements
                    self.change_dictionary['eliminate_singleton_equalities'][var_to_del]['deleted_variables_indices'] \
                        = index_original_columns_to_delete
                    self.change_dictionary['eliminate_singleton_equalities'][var_to_del]['deleted_rows_indices'] = (
                        index_original_rows_to_delete)
                else:
                    # Emit a warning indicating that the model is infeasible
                    warnings.warn("Model is infeasible due to a negative decision variable.",
                                  RuntimeWarning)
        self.change_dictionary['eliminate_singleton_equalities']['solutions'] = solution

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(("Eliminate Singleton Equalities", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_kton_equalities(self):
        """
        This function processes a Gurobi model to eliminate k-tons equality constraints.
        """

        # Variable to track if we found a kton in the current iteration
        found_kton = True

        # Dictionary to store solutions for ktons
        solution = {}

        while found_kton:
            found_kton = False

            # Getting the number of nonzero elements per row
            nonzero_count_per_row = np.count_nonzero(self.A.A, axis=1)

            # Create a boolean array where True indicates rows with k non-zero element
            k_nonzero = nonzero_count_per_row == self.k

            has_negative_counterpart, indices_list = find_corresponding_negative_rows_with_indices(self.A, self.b)

            # Combine the two conditions
            valid_rows = np.logical_and(k_nonzero, has_negative_counterpart)

            # Find indices where the element is True
            true_indices = np.where(valid_rows)[0]

            # Check if there are any True values and get the first index, else set to None
            first_kton_index = true_indices[0] if true_indices.size > 0 else None

            # Check if the equality kton row exists and process it
            if first_kton_index is not None:
                found_kton = True

                # Extract the kton row
                kton_row = self.A.A[first_kton_index, :]

                # identifying rows to delete
                index_rows_to_delete = [first_kton_index, indices_list[first_kton_index]]
                index_original_rows_to_delete = [self.original_row_index[first_kton_index],
                                                 self.original_row_index[indices_list[first_kton_index]]]

                # Identify the index of the last non-zero column (k)
                kton_column = np.nonzero(kton_row)[0][-1]
                index_original_columns_to_delete = self.original_column_index[kton_column]

                # Update the solution dictionary
                var_to_del = self.variable_names[kton_column]
                solution[var_to_del] = {"lhs": kton_row,
                                        "rhs": self.b[first_kton_index],
                                        "variables": self.variable_names}

                # Update the element "kton_row" of b
                self.b[first_kton_index] = self.b[first_kton_index] / self.A.A[first_kton_index, kton_column]

                # Update the row "kton_row" of A
                self.A[first_kton_index, :] = csr_matrix(
                    self.A.A[first_kton_index, :] / self.A.A[first_kton_index, kton_column])

                # Update the remaining rows/elements of A and b
                for i in range(self.A.A.shape[0]):
                    if i != first_kton_index:
                        self.b[i] -= self.A.A[i, kton_column] * self.b[first_kton_index]
                        self.A[i, :] -= csr_matrix(self.A.A[i, kton_column] * self.A.A[first_kton_index, :])

                # Update the objective function
                self.co += self.c[kton_column] * self.b[first_kton_index]

                # Update c
                self.c -= self.c[kton_column] * self.A.A[first_kton_index, :]
                self.c = self.c.tolist()

                # Update values by eliminating the variable "k_column"
                self.A = csr_matrix(np.delete(self.A.toarray(), kton_column, axis=1))
                del self.c[kton_column]
                self.lb = np.delete(self.lb, kton_column)
                self.ub = np.delete(self.ub, kton_column)
                del self.variable_names[kton_column]
                del self.original_column_index[kton_column]

                # Changing the constraint to <= --> similar to multiply A_i and b_i by -1 with >=
                self.A[first_kton_index, :] = -1 * self.A[first_kton_index, :]
                self.b[first_kton_index] = -1 * self.b[first_kton_index]

                # Remove the negative counterpart
                self.A = csr_matrix(np.delete(self.A.toarray(), index_rows_to_delete[-1], axis=0))
                del self.b[index_rows_to_delete[-1]]
                del self.cons_senses[index_rows_to_delete[-1]]
                del self.original_row_index[index_rows_to_delete[-1]]

                # Update change_dictionary with the information about deleted elements
                self.change_dictionary['eliminate_kton_equalities'][var_to_del]['deleted_variables_indices'] \
                    = index_original_columns_to_delete
                self.change_dictionary['eliminate_kton_equalities'][var_to_del]['deleted_rows_indices'] = (
                    index_original_rows_to_delete)
                self.change_dictionary['eliminate_kton_equalities']['solutions'] = solution

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(
            ("Eliminate Kton Equalities", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_singleton_inequalities(self):
        """
        This function processes a Gurobi model to eliminate singleton inequality constraints.
        It simplifies the model by removing redundant constraints and updating the model accordingly.
        """

        # Getting the number of nonzero elements per row
        nonzero_count_per_row = np.count_nonzero(self.A.A, axis=1)

        # Create a boolean array where True indicates rows with a single non-zero element
        single_nonzero = nonzero_count_per_row == 1

        has_negative_counterpart, indices_list = find_corresponding_negative_rows_with_indices(self.A, self.b)
        negated_list = [not x for x in has_negative_counterpart]

        # Combine the two conditions
        valid_rows = np.logical_and(single_nonzero, negated_list)

        num_rows, num_cols = self.A.A.shape

        to_delete_constraint = []
        to_delete_variable = []

        to_delete_constraint_original = []
        to_delete_variable_original = []

        for i in range(num_rows):

            if valid_rows[i]:
                # Extract the singleton row
                singleton_row = self.A.A[i, :]

                # Identify the index of the non-zero column (k)
                k_index = np.nonzero(singleton_row)[0][0]

                # Identify Aik
                A_ik = singleton_row[k_index]

                # Identify the right-hand-side
                b_i = self.b[i]

                if (A_ik > 0) and (b_i < 0):
                    to_delete_constraint.append(i)
                    to_delete_constraint_original.append(self.original_row_index[i])
                elif (A_ik < 0) and (b_i > 0):
                    warnings.warn("Model is infeasible due to a negative singleton inequality with a positive RHS.",
                                  RuntimeWarning)
                elif (A_ik > 0) and (b_i == 0):
                    to_delete_constraint.append(i)
                elif (A_ik < 0) and (b_i == 0):
                    to_delete_constraint.append(i)
                    to_delete_constraint_original.append(self.original_row_index[i])
                    to_delete_variable.append(k_index)
                    to_delete_variable_original.append(self.original_column_index[k_index])

        # Exclude constraints and variables
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_constraint, axis=0))
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_variable, axis=1))

        # Delete elements from b and the corresponding elements of the constraint operation
        # Iterating in reverse order to avoid index shifting issues
        for index in sorted(to_delete_constraint, reverse=True):
            del self.b[index]
            del self.cons_senses[index]
            del self.original_row_index[index]

        for index in sorted(to_delete_variable, reverse=True):
            del self.c[index]
            del self.lb[index]
            del self.ub[index]
            del self.variable_names[index]
            del self.original_column_index[index]

        # Update change_dictionary with the information about deleted elements
        self.change_dictionary['eliminate_singleton_inequalities']['deleted_variables_indices'] \
            = to_delete_variable_original
        self.change_dictionary['eliminate_singleton_inequalities']['deleted_rows_indices'] = (
            to_delete_constraint_original)

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(
            ("Eliminate Singleton Inequalities", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_dual_singleton_inequalities(self):
        """
        This function processes a Gurobi model to eliminate dual singleton inequality constraints.
        It simplifies the model by removing redundant variables and updating the model accordingly.
        """

        # Getting the number of nonzero elements per column
        nonzero_count_per_column = np.count_nonzero(self.A.A, axis=0)

        # Create a boolean array where True indicates rows with a single non-zero element
        valid_columns = nonzero_count_per_column == 1

        num_rows, num_cols = self.A.A.shape

        to_delete_constraint = []
        to_delete_variable = []

        to_delete_constraint_original = []
        to_delete_variable_original = []

        for j in range(num_cols):
            if valid_columns[j]:

                # Extract the singleton row
                singleton_column = self.A.A[:, j]

                # Identify the index row of the non-zero column (k)
                r_index = np.nonzero(singleton_column)[0][0]

                # Identify Aik
                A_ik = singleton_column[r_index]

                # Identify the cost
                c_j = self.c[j]

                if (A_ik > 0) and (c_j < 0):
                    warnings.warn("Model is infeasible due to a positive singleton column with a negative cost.",
                                  RuntimeWarning)
                elif (A_ik < 0) and (c_j > 0):
                    to_delete_variable.append(j)
                    to_delete_variable_original.append(self.original_column_index[j])
                elif (A_ik > 0) and (c_j == 0):
                    to_delete_variable.append(j)
                    to_delete_variable_original.append(self.original_column_index[j])
                    to_delete_constraint.append(r_index)
                    to_delete_constraint_original.append(self.original_row_index[r_index])
                elif (A_ik < 0) and (c_j == 0):
                    to_delete_variable.append(j)
                    to_delete_variable_original.append(self.original_column_index[j])

        # Exclude constraints and variables
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_constraint, axis=0))
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_variable, axis=1))

        # Delete elements from b and the corresponding elements of the constraint operation
        # Iterating in reverse order to avoid index shifting issues
        for index in sorted(to_delete_constraint, reverse=True):
            del self.b[index]
            del self.cons_senses[index]
            del self.original_row_index[index]

        for index in sorted(to_delete_variable, reverse=True):
            del self.c[index]
            del self.variable_names[index]
            del self.original_column_index[index]

        self.lb = np.delete(self.lb, to_delete_variable)
        self.ub = np.delete(self.ub, to_delete_variable)

        # Update change_dictionary with the information about deleted elements
        self.change_dictionary['eliminate_dual_singleton_inequalities']['deleted_variables_indices'] \
            = to_delete_variable_original
        self.change_dictionary['eliminate_dual_singleton_inequalities']['deleted_rows_indices'] = (
            to_delete_constraint_original)

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(
            ("Eliminate Dual Singleton Inequalities", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_redundant_columns(self):
        """
        Eliminates redundant columns and constraints from a linear programming model based on the provided conditions.
        """

        # Create boolean arrays for each condition
        b_zero = np.array(self.b) == 0  # True for rows where b_i = 0

        # For each row, check if all non-zero elements are non-negative or all are non-positive
        non_negative_elements = np.all(self.A.A >= 0, axis=1)
        non_positive_elements = np.all(self.A.A <= 0, axis=1)

        # boolean for equalities
        has_negative_counterpart, indices_list = find_corresponding_negative_rows_with_indices(self.A, self.b)

        # Combined condition: True for rows where b_i = 0 and all elements are non-negative or all are non-positive
        combined_condition = b_zero & has_negative_counterpart & (non_negative_elements | non_positive_elements)

        to_delete_constraint = []
        to_delete_variable = []

        to_delete_constraint_original = []
        to_delete_variable_original = []

        num_rows, num_cols = self.A.A.shape

        for i in range(num_rows):
            if combined_condition[i]:
                # finding the constraints to remove
                if i not in to_delete_constraint:
                    to_delete_constraint.append(i)
                    to_delete_constraint_original.append(self.original_row_index[i])

                # finding nonnull variables on that constraint to remove
                non_zero_variables = np.nonzero(self.A.A[i, :])[0]
                for index in non_zero_variables:
                    if index not in to_delete_variable:
                        to_delete_variable.append(index)
                        to_delete_variable_original.append(self.original_column_index[index])

        # Exclude constraints and variables
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_constraint, axis=0))
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_variable, axis=1))

        # Delete elements from b and the corresponding elements of the constraint operation
        # Iterating in reverse order to avoid index shifting issues
        for index in sorted(to_delete_constraint, reverse=True):
            del self.b[index]
            del self.cons_senses[index]
            del self.original_row_index[index]

        self.lb = np.delete(self.lb, to_delete_variable)
        self.ub = np.delete(self.ub, to_delete_variable)

        for index in sorted(to_delete_variable, reverse=True):
            del self.c[index]
            del self.variable_names[index]
            del self.original_column_index[index]

        # Update change_dictionary with the information about deleted elements
        self.change_dictionary['eliminate_redundant_columns']['deleted_variables_indices'] \
            = to_delete_variable_original
        self.change_dictionary['eliminate_redundant_columns']['deleted_rows_indices'] = (
            to_delete_constraint_original)

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(
            ("Eliminate Redundant Columns", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_implied_bounds(self, feasibility_tolerance=1e-6, infinity=1e30):
        """
        Analyzes each constraint in a Gurobi model and categorizes them as valid, redundant, or infeasible.

        Parameters:
        feasibility_tolerance (float, optional): Tolerance used to assess feasibility. Defaults to 1e-6.
        infinity (float, optional): Value representing infinity in the context of the model. Defaults to 1e30.
        """

        # Get row activities from the model
        SUPP, INF, SUP = self.get_row_activities()

        to_delete_constraint = []
        to_delete_constraint_original = []

        num_rows, num_cols = self.A.A.shape

        for i in range(num_rows):

            if self.b[i] >= infinity:
                to_delete_constraint.append(i)
                to_delete_constraint_original.append(self.original_row_index[i])

            if INF[i] > (self.b[i] + feasibility_tolerance):
                to_delete_constraint.append(i)
                to_delete_constraint_original.append(self.original_row_index[i])

            if SUP[i] < (self.b[i] + feasibility_tolerance):
                warnings.warn(f"Model is infeasible: The superior of the constraint {i} is inferior to its RHS.",
                              RuntimeWarning)

        # Exclude constraints
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_constraint, axis=0))

        # Delete elements from b and the corresponding elements of the constraint operation
        # Iterating in reverse order to avoid index shifting issues
        for index in sorted(to_delete_constraint, reverse=True):
            del self.b[index]
            del self.cons_senses[index]
            del self.original_row_index[index]

        # Update change_dictionary with the information about deleted elements
        self.change_dictionary['eliminate_implied_bounds']['deleted_rows_indices'] = (
            to_delete_constraint_original)

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(
            ("Eliminate Implied Bounds", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def eliminate_redundant_rows(self):
        """
        Eliminates redundant rows from a linear programming model's constraints matrix.
        """

        dependent_rows, has_linear_dependency = linear_dependency(self.A, self.b)

        # boolean for equalities
        has_negative_counterpart, indices_list = find_corresponding_negative_rows_with_indices(self.A, self.b)

        to_delete_constraint = []
        to_delete_constraint_original = []

        num_rows, num_cols = self.A.A.shape

        # Iterate over the constraints
        for i in range(num_rows):
            if i not in to_delete_constraint:
                if has_linear_dependency[i]:
                    list_of_dependencies = dependent_rows[i]
                    negative_counterpart_index = indices_list[i]
                    for j in list_of_dependencies:
                        if j != negative_counterpart_index:
                            if j not in to_delete_constraint:
                                to_delete_constraint.append(j)
                                to_delete_constraint_original.append(self.original_row_index[j])

        # Exclude constraints
        self.A = csr_matrix(np.delete(self.A.toarray(), to_delete_constraint, axis=0))

        # Delete elements from b and the corresponding elements of the constraint operation
        # Iterating in reverse order to avoid index shifting issues
        for index in sorted(to_delete_constraint, reverse=True):
            del self.b[index]
            del self.cons_senses[index]
            del self.original_row_index[index]

        # Update change_dictionary with the information about deleted elements
        self.change_dictionary['eliminate_redundant_rows']['deleted_rows_indices'] = (
            to_delete_constraint_original)

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(
            ("Eliminate Redundant Rows", len(self.cons_senses), len(self.variable_names), self.A.nnz))

    def reduction_small_coefficients(self, threshold=5*10e-2):

        A_norm, _, _ = normalize_features(self.A, self.b)

        self.A = matrix_sparsification(threshold, A_norm, self.A)

        # Update operation table with the number of variables and constraints after this operation
        self.operation_table.append(
            ("reduction Small Coefficients", len(self.cons_senses), len(self.variable_names), self.A.nnz))
