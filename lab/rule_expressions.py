"""Bounded, exact rule expressions. No text evaluation or game defaults."""
from fractions import Fraction

FIELDS = frozenset({"hp", "max_hp", "energy", "max_energy", "status.poison", "status.freeze", "status.burn", "status.leech", "effect.poison"})
OPS = frozenset({"add", "sub", "mul", "min", "max"})
COMPARISONS = frozenset({"eq", "lt", "lte", "gt", "gte"})
MAX_DEPTH = 16
MAX_NODES = 128
MAX_BITS = 256


def _number(value):
    if type(value) is int:
        result = Fraction(value)
    elif isinstance(value, dict) and set(value) == {"numerator", "denominator"}:
        if type(value["numerator"]) is not int or type(value["denominator"]) is not int or value["denominator"] <= 0:
            raise ValueError("Expression ratio requires integers and a positive denominator")
        result = Fraction(value["numerator"], value["denominator"])
    else:
        raise ValueError("Expression number must be an integer or explicit rational; floats/bools are not accepted")
    if max(abs(result.numerator).bit_length(), result.denominator.bit_length()) > MAX_BITS:
        raise ValueError("Expression numeric budget exceeded")
    return result


def _visit(node, kind, budget, depth):
    budget[0] += 1
    if depth > MAX_DEPTH or budget[0] > MAX_NODES:
        raise ValueError("Expression tree budget exceeded")
    if not isinstance(node, dict):
        raise ValueError("Expression node must be an object")
    keys = set(node)
    if kind == "expression":
        if keys == {"const"}:
            _number(node["const"])
        elif keys == {"read"}:
            read = node["read"]
            if (not isinstance(read, dict) or set(read) != {"target", "field"}
                    or read["target"] not in ("self", "opponent") or read["field"] not in FIELDS):
                raise ValueError("Expression read must name an explicit actor resource")
        elif keys == {"op", "args"}:
            if node["op"] not in OPS or not isinstance(node["args"], list) or len(node["args"]) != 2:
                raise ValueError("Expression operation requires two operands and a supported operator")
            for child in node["args"]:
                _visit(child, kind, budget, depth + 1)
        else:
            raise ValueError("Unknown expression syntax")
    elif keys == {"compare", "left", "right"}:
        if node["compare"] not in COMPARISONS:
            raise ValueError("Unknown comparison")
        for name in ("left", "right"):
            _visit(node[name], "expression", budget, depth + 1)
    elif keys in ({"all"}, {"any"}):
        values = node[next(iter(keys))]
        if not isinstance(values, list) or not values:
            raise ValueError("Condition group must not be empty")
        for child in values:
            _visit(child, "condition", budget, depth + 1)
    elif keys == {"not"}:
        _visit(node["not"], "condition", budget, depth + 1)
    else:
        raise ValueError("Unknown condition syntax")


def validate_expression(expression):
    _visit(expression, "expression", [0], 0)


def validate_condition(condition):
    _visit(condition, "condition", [0], 0)


def _evaluate(node, state):
    if "const" in node:
        return _number(node["const"])
    if "read" in node:
        read = node["read"]
        actor = state.get(read["target"])
        if read['field'] == 'effect.poison':
            from lab.mark_runtime import layer_count
            if not isinstance(actor, dict) or not isinstance(actor.get('statuses'), dict) or 'field_marks' not in actor:
                raise ValueError('Poison-effect expression requires explicit status and field mark snapshots')
            count = actor['statuses'].get('poison', 0)
            if type(count) is not int or count < 0:
                raise ValueError('Invalid poison status layer count')
            return _number(count + layer_count(actor, 1014))
        if read['field'].startswith('status.'):
            if not isinstance(actor, dict) or not isinstance(actor.get('statuses'), dict):
                raise ValueError('Status expression requires an explicit status snapshot')
            value = actor['statuses'].get(read['field'].split('.')[1], 0)
            if type(value) is not int or value < 0:
                raise ValueError('Status expression requires nonnegative integer layers')
            return _number(value)
        if not isinstance(actor, dict) or read["field"] not in actor:
            raise ValueError("Missing state resource for expression read")
        return _number(actor[read["field"]])
    left, right = (_evaluate(child, state) for child in node["args"])
    result = {"add": lambda: left + right, "sub": lambda: left - right,
              "mul": lambda: left * right, "min": lambda: min(left, right),
              "max": lambda: max(left, right)}[node["op"]]()
    return _number({"numerator": result.numerator, "denominator": result.denominator})


def evaluate_expression(expression, state, event=None):
    validate_expression(expression)
    return _evaluate(expression, state)


def _condition(node, state):
    if "compare" in node:
        left, right = _evaluate(node["left"], state), _evaluate(node["right"], state)
        return {"eq": lambda: left == right, "lt": lambda: left < right, "lte": lambda: left <= right,
                "gt": lambda: left > right, "gte": lambda: left >= right}[node["compare"]]()
    # Evaluate all branches so an absent state value cannot hide in short-circuit logic.
    if "all" in node:
        return all([_condition(child, state) for child in node["all"]])
    if "any" in node:
        return any([_condition(child, state) for child in node["any"]])
    return not _condition(node["not"], state)


def evaluate_condition(condition, state, event=None):
    validate_condition(condition)
    return _condition(condition, state)
