import csv
import math
import os
from collections import Counter, defaultdict

STRATEGIES = ("MILL", "BLOCK", "CAPTURE", "MOVE", "RANDOM")

class BayesianNetwork:
    r"""
    Small discrete Bayesian Network for predicting the human's next strategy.

    Structure:
        stage
        human_threat
        ai_threat
        piece_advantage
        last_move_type
              \ | /
               v
        human_strategy

    We estimate P(strategy | features) using a Naive-Bayes style conditional
    factorization with Laplace smoothing. It is intentionally transparent
    and easy to demonstrate in a project viva.
    r"""

    def __init__(self, csv_path=None):
        self.rows = []
        self.counts = defaultdict(Counter)
        self.strategy_counts = Counter()
        self.total = 0
        # Value domains per feature (for correct Laplace smoothing).
        self.domains = defaultdict(set)
        self.domains["stage"].update(("PLACEMENT", "MOVEMENT", "FLYING"))
        for f in ("human_threat", "ai_threat"):
            self.domains[f].update(("LOW", "MEDIUM", "HIGH"))
        self.domains["piece_advantage"].update(("HUMAN", "AI", "EQUAL"))
        self.domains["last_move_type"].update(("MOVE", "NONE"))
        if csv_path and os.path.exists(csv_path):
            self.load_csv(csv_path)

    def load_csv(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.learn(row)

    def learn(self, row):
        strategy = row["strategy"]
        self.strategy_counts[strategy] += 1
        self.total += 1
        for feature in ("stage", "human_threat", "ai_threat", "piece_advantage", "last_move_type"):
            self.counts[(feature, strategy)][row[feature]] += 1
            self.domains[feature].add(row[feature])

    def posterior(self, features):
        if self.total == 0:
            return {s: 1 / len(STRATEGIES) for s in STRATEGIES}

        result = {}
        k = len(STRATEGIES)
        for strategy in STRATEGIES:
            prior = (self.strategy_counts[strategy] + 1) / (self.total + k)
            logp = math.log(prior)

            for feature, value in features.items():
                table = self.counts[(feature, strategy)]
                denominator = self.strategy_counts[strategy] + max(2, len(self.domains[feature]))
                probability = (table[value] + 1) / denominator
                logp += math.log(probability)

            result[strategy] = math.exp(logp)

        total = sum(result.values())
        return {s: result[s] / total for s in result}

    def predict(self, features):
        probabilities = self.posterior(features)
        return max(probabilities, key=probabilities.get), probabilities

    def update_from_observation(self, features, strategy):
        row = dict(features)
        row["strategy"] = strategy
        self.learn(row)

    def predict_board(self, board, stage, last_move_type="MOVE"):
        return self.predict(self.board_features(board, stage, last_move_type))

    def board_features(self, board, stage, last_move_type="MOVE"):
        from game.board import potential_mills
        from game.rules import HUMAN, AI, count_pieces

        h_mills = potential_mills(board, HUMAN)
        a_mills = potential_mills(board, AI)

        human_threat = "HIGH" if h_mills >= 2 else "MEDIUM" if h_mills == 1 else "LOW"
        ai_threat = "HIGH" if a_mills >= 2 else "MEDIUM" if a_mills == 1 else "LOW"

        hp = count_pieces(board, HUMAN)
        ap = count_pieces(board, AI)
        if hp > ap:
            advantage = "HUMAN"
        elif ap > hp:
            advantage = "AI"
        else:
            advantage = "EQUAL"

        features = {
            "stage": stage,
            "human_threat": human_threat,
            "ai_threat": ai_threat,
            "piece_advantage": advantage,
            "last_move_type": last_move_type,
        }
        return features

    def human_strategy_from_move(self, before, after, move, stage):
        from game.board import forms_mill, potential_mills
        from game.rules import HUMAN, AI

        if move.kind == "place":
            target = move.target
        else:
            target = move.target

        if forms_mill(after, target, HUMAN):
            return "MILL"

        before_h = potential_mills(before, HUMAN)
        after_h = potential_mills(after, HUMAN)
        before_ai = potential_mills(before, AI)
        after_ai = potential_mills(after, AI)

        if after_ai < before_ai:
            return "BLOCK"
        if after_h > before_h:
            return "MILL"
        if after.count(AI) < before.count(AI):
            return "CAPTURE"
        if move.kind == "move":
            return "MOVE"
        return "RANDOM"
