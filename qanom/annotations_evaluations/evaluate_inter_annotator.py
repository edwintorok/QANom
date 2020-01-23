from argparse import ArgumentParser
from collections import defaultdict, Counter
from itertools import combinations, permutations
from typing import List, Dict, Any

import pandas as pd

from annotations_evaluations.argument_first_evaluation import eval_datasets
from annotations_evaluations.common import read_annot_csv
from annotations_evaluations.decode_encode_answers import decode_qasrl
from annotations_evaluations.evaluate import Metrics, BinaryClassificationMetrics

""" Helper funcs for important information within an annotation DataFrame """
def get_sent_map(annot_df: pd.DataFrame) -> Dict[str, List[str]]:
    sent_map = dict(zip(annot_df.qasrl_id, annot_df.sentence.apply(str.split)))
    return sent_map

def set_n_workers(df: pd.DataFrame) -> pd.DataFrame:
    # per predicate
    cols = ['qasrl_id', 'verb_idx']
    df['n_workers'] = df.groupby(cols).worker_id.transform(pd.Series.nunique)
    return df

def set_n_roles(df: pd.DataFrame) -> pd.DataFrame:
    # per predicate per worker
    cols = ['qasrl_id', 'verb_idx']
    df['n_roles'] = df.groupby(cols + ['worker_id']).verb.transform(pd.Series.count)
    return df

def get_n_predicates(df: pd.DataFrame) -> int:
    # overall
    cols = ['qasrl_id', 'verb_idx']
    return df[cols].drop_duplicates().shape[0]

def get_n_positive_predicates(worker_df: pd.DataFrame) -> int:
    # gets a df of a single worker, returns number of isVerbal==True in his annotations
    reduced_df = worker_df.drop_duplicates(subset=["key"])
    n_positive_predicates = reduced_df.is_verbal.sum()
    return n_positive_predicates

# describe statistics of the saved annotated data
def get_worker_statistics(annot_df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    df = annot_df
    if 'key' not in df.columns:
        df['key'] = df.apply(lambda r: r['qasrl_id']+"_"+str(r['verb_idx']), axis=1)
    by_worker = df.groupby("worker_id")
    num_of_predicates = by_worker.key.nunique()
    num_of_qas = by_worker.question.count() # counts only non-NA values
    workers = list(num_of_predicates.index)
    return {worker:
                {"num-predicates": num_of_predicates[worker],
                 "num-QAs": num_of_qas[worker]}
            for worker in workers}

def get_worker_statistics_from_file(anot_fn):
    return get_worker_statistics(read_annot_csv(anot_fn))

""" Analysis functions"""


def describe_worker_work(annot_df: pd.DataFrame):
    cols = ['qasrl_id', 'verb_idx']
    sent_map: Dict[str, List[str]] = get_sent_map(annot_df)
    workers = annot_df.worker_id.unique().tolist()
    agreement_stats = evaluate_per_worker_iaa(annot_df, isPrinting=False)
    general_worker_stats = get_worker_statistics(annot_df)
    for worker in workers:
        """ For each worker, present:
         - # predicates
         - # of predicates judged positive (as verbal nouns)
         - # distribution of #-roles per positive predicate
        """
        print(f"********** Worker {worker}: ************")
        df: pd.DataFrame = annot_df[annot_df.worker_id == worker]
        n_predicates = get_n_predicates(df)
        n_positive_predicates = get_n_positive_predicates(df)
        roleDist = Counter(df[df.is_verbal].groupby('key').agg(pd.Series.count)['question'])
        sum_roles = sum(k*v for k,v in roleDist.items())
        num_roles_average = sum_roles / float(n_positive_predicates)
        print(f'#-predicates: {n_predicates}')
        print(f'#-positive predicates: {n_positive_predicates} , ({float(n_positive_predicates)/n_predicates:.2f})')
        print(f'#-Roles per predicate Distribution: {roleDist}')
        print(f'#-Roles average (for positive predicates): {num_roles_average:.2f}')
        print(agreement_stats[worker])
    #  todo complete it with more info?


def evaluate_per_worker_iaa(annot_df: pd.DataFrame, isPrinting=True):
    cols = ['qasrl_id', 'verb_idx']
    sent_map: Dict[str, List[str]] = get_sent_map(annot_df)
    workers = annot_df.worker_id.unique().tolist()
    n_workers = len(workers)
    n_predicates = get_n_predicates(annot_df)
    print("n_workers: ", n_workers)
    print("n_predicates: ", n_predicates)

    # save per worker a list of local 1:1 inter-annotator agreement and their weights (i.e. number of instances);
    arg_agreements = defaultdict(list)
    nom_ident_agreements = defaultdict(list)
    # go through all pairs of workers - permutations (less efficient then combinations, but more readable)
    for w1, w2 in permutations(workers, r=2):
        w1_df = annot_df[annot_df.worker_id == w1].copy()
        w2_df = annot_df[annot_df.worker_id == w2].copy()
        # compute 1:1 agreements
        arg_metrics, role_metrics, nom_ident_metrics, matching_args = eval_datasets(w1_df, w2_df, sent_map, allow_overlaps=False)
        #matching_args['key'] = matching_args.apply(lambda r: r['qasrl_id']+"_"+str(r['verb_idx']), axis=1)
        # Arg-Accuracy: metric is f1, weight is number of predicted arguments
        arg_agreements[w1].append(arg_metrics)
        # Nominalization-Identification Accuracy: metric is accuracy, weight is number of (common) predicates
        nom_ident_agreements[w1].append(nom_ident_metrics)
    # compute per worker personal performance, measured by IAA
    worker_arg_performance = {}
    for worker_id, lst_of_agreements in arg_agreements.items():
        overallArgMetric : Metrics = sum(lst_of_agreements)
        worker_arg_performance[worker_id] = overallArgMetric
    worker_isnom_performance = {}
    for worker_id, lst_of_accMetrics in nom_ident_agreements.items():
        total_acc_metric : BinaryClassificationMetrics = sum(lst_of_accMetrics)
        worker_isnom_performance[worker_id] = total_acc_metric

    # print and save statistics
    print(f"worker_id \t\t arg \t\t\t\t is_verbal")
    worker_general_statistics = get_worker_statistics(annot_df)
    for worker_id, statistics in worker_general_statistics.items():
        if isPrinting:
            print(f"{worker_id} \t arg: {worker_arg_performance[worker_id]} " +
                  f"\t is-verbal accuracy: {worker_isnom_performance[worker_id].accuracy():.3f} " +
                  f"({statistics['num-predicates']} predicates, " +
                  f"{statistics['num-QAs']} QAs)")
        worker_general_statistics[worker_id].update({"arg-agreement": worker_arg_performance[worker_id],
                                                     "is-verbal accuracy": worker_isnom_performance[worker_id].accuracy()})
    return worker_general_statistics


def evaluate_generator_agreement(annot_df: pd.DataFrame, verbose: bool = False):
    cols = ['qasrl_id', 'verb_idx']
    sent_map: Dict[str, List[str]] = get_sent_map(annot_df)
    n_gen = annot_df.groupby(cols).worker_id.transform(pd.Series.nunique)
    workers = annot_df.worker_id.unique().tolist()
    n_workers = len(workers)
    annot_df = annot_df.copy()
    n_predicates = annot_df[cols].drop_duplicates().shape[0]
    if verbose:
        print("n_workers: ", n_workers)
        print("n_predicates: ", n_predicates)
        print(f"metric\tworker_1\tworker_2\tprec\trecall\tf1")

    total_arg_metric = Metrics.empty()
    total_role_metric = Metrics.empty()
    total_nomIdent_metric : BinaryClassificationMetrics = BinaryClassificationMetrics.empty()
    for w1, w2 in combinations(workers, r=2):
        w1_df = annot_df[annot_df.worker_id == w1].copy()
        w2_df = annot_df[annot_df.worker_id == w2].copy()
        arg_metrics, role_metrics, nom_ident_metrics, _ = eval_datasets(w1_df, w2_df, sent_map, allow_overlaps=False)
        if verbose:
            print(f"\nComparing  {w1}   to   {w2}:   [p,r,f1]")
            print(f"Number of shared predicates: {get_n_predicates(pd.merge(w1_df, w2_df, on=cols))}")
            print(f"ARG:\t{arg_metrics.prec():.3f}\t{arg_metrics.recall():.3f}\t{arg_metrics.f1():.3f}")
            print(f"ROLE:\t{role_metrics.prec():.3f}\t{role_metrics.recall():.3f}\t{role_metrics.f1():.3f}")
            print(f"NOM_IDENT:\t{w1}\t{w2}\t{nom_ident_metrics.prec():.3f}\t{nom_ident_metrics.recall():.3f}\t{nom_ident_metrics.f1():.3f}")
            print(f"NOM_IDENT accuracy: {nom_ident_metrics.accuracy():.3f}, {int(nom_ident_metrics.errors())} mismathces out of {nom_ident_metrics.instances()} predicates.")
        total_arg_metric += arg_metrics
        total_role_metric += role_metrics
        total_nomIdent_metric += nom_ident_metrics

    print(f"\nOverall pairwise agreement:")
    print(f"arg-f1 : {total_arg_metric.f1():.4f}")
    print(f"role-f1 : {total_role_metric.f1():.4f}")
    print(f"is-verbal-accuracy: {total_nomIdent_metric.accuracy():.4f}    for {total_nomIdent_metric.instances()} pairwise comparisons.")



def main(annotation_path: str):
    annot_df = read_annot_csv(annotation_path)
    annot_df = decode_qasrl(annot_df)
    # original annotations, multiple generation tasks per predicate
    print(annot_df.worker_id.value_counts())
    evaluate_generator_agreement(annot_df, verbose=True)

def main_iaa_per_worker(annotation_path: str):
    annot_df = read_annot_csv(annotation_path)
    annot_df = decode_qasrl(annot_df)
    print(annot_df.worker_id.value_counts())
    evaluate_per_worker_iaa(annot_df)

if __name__ == "__main__":
    ap = ArgumentParser()
    ap.add_argument("annotation_path")
    args = ap.parse_args()
    main(args.annotation_path)

