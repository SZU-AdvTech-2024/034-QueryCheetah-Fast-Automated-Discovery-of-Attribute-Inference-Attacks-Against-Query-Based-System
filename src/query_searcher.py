import numpy as np
import tqdm
from multiprocessing import Pool

import src.utils


class QuerySearcher:

    @staticmethod
    def search_for_this_syntax(args, aux_value_probabilities, column_names, continuous_columns, final_qbses, final_ys,
                               seed, target_record, start_queue_of_queries, start_query2query_answers, indexes):
        """
        For easier computation, instead of generating k queries at each iteration to replace the least important
        queries, we generate a queue of queries before we start the search and use them for the replacement.
        First we generate a queue of queries.
        Second, we evaluate their answers on the
        shadow QBSs protecting D_1^{train}, ..., D_f^{train} and D_1^{val}, ..., D_g^{val}.
        Third, we use them in the search.
        """

        # (1) generate a queue of queries
        queue_of_queries = QuerySearcher.construct_queue_of_queries(args, column_names, target_record,
                                                                    continuous_columns, aux_value_probabilities, seed,
                                                                    start_queue_of_queries)
        query2query_answers = {}

        # (2) evaluate the queries (Parallelize evaluation)
        queue_of_queries = start_queue_of_queries + queue_of_queries
        query2query_answers.update(start_query2query_answers)

        # Parallelize query evaluations
        with Pool(args.num_procs) as pool:
            results = pool.starmap(src.utils.evaluate_queries,
                                  [(queue_of_queries[i:i + args.num_queries], final_qbses, args.num_procs, query2query_answers, indexes)
                                   for i in range(0, len(queue_of_queries), args.num_queries)])

        # (3) use the queries in the search
        starting_solution = queue_of_queries[:args.num_queries]
        queue_of_queries_pointer = args.num_queries
        all_accuracies, best_solution, best_index = QuerySearcher.search_from_solution(starting_solution, 0,
                                                                                       final_qbses, final_ys,
                                                                                       args,
                                                                                       target_record, column_names,
                                                                                       queue_of_queries,
                                                                                       queue_of_queries_pointer,
                                                                                       query2query_answers,
                                                                                       continuous_columns,
                                                                                       aux_value_probabilities,
                                                                                       args.change_k_queries_at_each_iteration,
                                                                                       indexes)
        query2query_answers_dump = {query: query_answers for (query, query_answers) in query2query_answers.items() if
                                    query in best_solution}
        return all_accuracies, best_index, best_solution, query2query_answers_dump, min(all_accuracies[best_index][0],
                                                                                        all_accuracies[best_index][1])

    @staticmethod
    def construct_queue_of_queries(args, column_names, target_record, continuous_columns,
                                   aux_value_probabilities, seed, start_queue_of_queries):
        np.random.seed(seed)
        number_of_queries = args.num_queries + args.change_k_queries_at_each_iteration * args.num_iterations - len(
            start_queue_of_queries)
        queries = [QuerySearcher.get_random_query(column_names, args.use_target_user_values,
                                                  target_record,
                                                  continuous_columns, aux_value_probabilities,
                                                  args.use_operator_in,
                                                  args.use_operator_between, args.use_neq_multiple_times,
                                                  args.use_limited_syntax_fast_qbs) for _ in
                   range(number_of_queries)]
        return queries

    @staticmethod
    def get_random_query(column_names, use_target_user_values,
                         target_record, continuous_columns, aux_value_probabilities,
                         use_operator_in,
                         use_operator_between, use_neq_multiple_times, use_limited_syntax_fast_qbs):
        if use_limited_syntax_fast_qbs:
            return tuple(np.random.choice([-1, 0, 1], size=len(column_names), replace=True))
        comparisons = []
        floating_columns = ['id']

        for column_name in column_names:
            options_for_column_to_compare_to_two_values = []
            if use_operator_between and column_name in continuous_columns:
                options_for_column_to_compare_to_two_values.append(0)
            if use_operator_in:
                options_for_column_to_compare_to_two_values.append(1)
            if use_neq_multiple_times:
                options_for_column_to_compare_to_two_values.append(2)

            num_values_the_column_compares_to = np.random.choice([0, 1, 2], p=[1 / 3, 1 / 3, 1 / 3])

            if num_values_the_column_compares_to == 0:
                continue
            elif num_values_the_column_compares_to == 1:
                comparison_operator = np.random.choice(["!=", "="])
                value = QuerySearcher._get_values(use_target_user_values, target_record, column_name,
                                                  num_values_the_column_compares_to,
                                                  comparison_operator)
                comparisons.append(f'{column_name} {comparison_operator} {value:.7g}')
            else:  # num_values_the_column_compares_to >= 2:
                option_for_column_to_appear_twice = np.random.choice(options_for_column_to_compare_to_two_values)
                if option_for_column_to_appear_twice == 0:  # BETWEEN
                    value1, value2 = QuerySearcher._get_values(use_target_user_values, target_record, column_name,
                                                               num_values_the_column_compares_to,
                                                               None)
                    comparisons.append(f'{column_name} BETWEEN {value1:.7g} AND {value2:.7g}')
                elif option_for_column_to_appear_twice == 1:  # IN
                    floating_columns.append(column_name)
                    value1, value2 = QuerySearcher._get_values_for_in_and_notin(aux_value_probabilities, column_name,
                                                                                target_record, use_target_user_values)
                    comparisons.append(f'{column_name} IN ({value1:.7g}, {value2:.7g})')
                elif option_for_column_to_appear_twice == 2:  # NOT IN
                    value1, value2 = QuerySearcher._get_values_for_in_and_notin(aux_value_probabilities, column_name,
                                                                                target_record, use_target_user_values)
                    comparisons.append(f'{column_name} != {value1:.7g}')
                    comparisons.append(f'{column_name} != {value2:.7g}')
                else:
                    raise NotImplementedError()

        query = f"SELECT {', '.join(floating_columns)} FROM data"
        if len(comparisons) == 0:
            return query
        q = f'{query} WHERE {" and ".join(comparisons)}'
        return q

    @staticmethod
    def _get_values_for_in_and_notin(aux_value_probabilities, column_name, target_record, use_target_user_values):
        value1 = target_record[column_name] if column_name != 'sens' else 1
        l = [i for (i, c) in enumerate(aux_value_probabilities[column_name].keys()) if c == value1]
        indx = l[0] if len(l) == 1 else None
        coin_flip = np.random.choice([0, 1])
        if coin_flip == 0:
            value2 = np.random.choice(
                [c for (i, c) in enumerate(aux_value_probabilities[column_name].keys()) if i != indx],
                p=QuerySearcher.softmax(np.array(
                    [c for (i, c) in enumerate(aux_value_probabilities[column_name].values()) if
                     i != indx])))

        else:
            value2 = -1000000
        if use_target_user_values:
            value2 = value1
        return value1, value2

    @staticmethod
    def _get_values(use_target_user_values, target_record, column_name, times_it_will_appear, comparison_operators):
        center = target_record[column_name] if column_name != 'sens' else 1
        if use_target_user_values:
            if times_it_will_appear == 1:
                return center
            else:
                return center, center

        order_of_magnitude = np.random.choice([-2, -1, 0])
        possible_width_values = np.array([1, 2, 5]) * (10 ** int(order_of_magnitude))
        width = np.random.choice(possible_width_values)

        k1 = np.rint(center / (2 * width))
        offset1 = k1 * 2 * width
        k2 = np.rint((2 * center - width) / (4 * width))
        offset2 = width * (2 * k2 + 0.5)

        if abs(center - offset1) < abs(center - offset2):
            offset = offset1
        else:
            offset = offset2
        values = [offset, offset + width]

        if times_it_will_appear == 1:
            if comparison_operators == '=':
                return center
            elif comparison_operators == '!=':
                coin_flip = np.random.choice([0, 1])
                if coin_flip == 0:
                    return center
                elif coin_flip == 1:
                    return offset
            else:
                coin_flip = np.random.choice([0, 1])
                if coin_flip == 0:
                    return center
                elif coin_flip == 1:
                    return offset
        elif times_it_will_appear == 2:
            return values
        else:
            raise NotImplementedError()

    @staticmethod
    def search_from_solution(starting_solution, current_iteration, final_qbses, final_ys, args, target_record,
                             column_names, queue_of_queries, queue_of_queries_pointer, query2query_answers,
                             continuous_columns, aux_value_probabilities, change_k_queries_at_each_iteration, indexes):
        """
        Iterative query selection and optimization.
        """
        solution = starting_solution
        all_accuracies = []
        for i in tqdm.tqdm(range(current_iteration, args.num_iterations), ncols=80):
            accuracies_for_this_iteration = []
            for _ in range(change_k_queries_at_each_iteration):
                solution, accuracies_for_this_iteration = QuerySearcher.update_solution(solution, queue_of_queries,
                                                                                      queue_of_queries_pointer,
                                                                                      query2query_answers,
                                                                                      final_qbses, final_ys,
                                                                                      aux_value_probabilities,
                                                                                      continuous_columns,
                                                                                      target_record,
                                                                                      column_names, indexes)
            all_accuracies.append(accuracies_for_this_iteration)
            queue_of_queries_pointer = (queue_of_queries_pointer + change_k_queries_at_each_iteration) % len(
                queue_of_queries)

        best_index = np.argmin([accuracy[0] for accuracy in all_accuracies])
        best_solution = solution
        return all_accuracies, best_solution, best_index

    @staticmethod
    def update_solution(solution, queue_of_queries, queue_of_queries_pointer, query2query_answers, final_qbses, final_ys,
                        aux_value_probabilities, continuous_columns, target_record, column_names, indexes):
        """
        Select the best query from the queue and update the solution.
        """
        new_query = queue_of_queries_pointer % len(queue_of_queries)
        solution.append(new_query)
        # Update accuracies for solution
        accuracies_for_this_query = src.utils.evaluate_queries([queue_of_queries[new_query]], final_qbses, len(solution), query2query_answers, indexes)
        return solution, accuracies_for_this_query

    @staticmethod
    def softmax(x):
        """Computes softmax values for each set of scores in x."""
        e_x = np.exp(x - np.max(x))  # Numerical stability
        return e_x / e_x.sum(axis=0, keepdims=True)