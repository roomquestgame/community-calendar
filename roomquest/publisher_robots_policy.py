"""Robots permission matching for the guarded publisher transport.

RFC 9309 sections 2.2.1–2.2.3 require wildcard paths, group merging and the
most-specific rule. urllib.robotparser treats path wildcards literally and
uses the first matching rule, so it cannot decide these permissions.
HTTP failures, policy cache lifetime and crawl-delay remain the worker's job.
"""
from dataclasses import dataclass
from string import ascii_letters, digits, hexdigits
from urllib.parse import quote, urlsplit


_UNRESERVED = frozenset(ascii_letters + digits + "-._~")
_URI_LITERAL = _UNRESERVED | frozenset("/:?@!&'()+,;=")


def _normalize_octets(value):
    """Decode only unreserved escapes; retain reserved/non-ASCII octets.

    Literal '*' and '$' in a URL use their escaped forms so that a rule containing
    %2A or %24 matches them without turning those escapes into pattern operators.
    """
    result = []
    index = 0
    while index < len(value):
        char = value[index]
        if (char == "%" and index + 2 < len(value)
                and all(part in hexdigits for part in value[index + 1:index + 3])):
            octet = value[index + 1:index + 3]
            decoded = chr(int(octet, 16))
            result.append(decoded if decoded in _UNRESERVED else "%" + octet.upper())
            index += 3
            continue
        result.append(char if char in _URI_LITERAL else quote(char, safe=""))
        index += 1
    return "".join(result)


@dataclass(frozen=True)
class _Rule:
    parts: tuple[str, ...]
    anchored: bool
    specificity: int
    allow: bool

    @classmethod
    def from_path(cls, path, allow):
        anchored = path.endswith("$")
        body = path[:-1] if anchored else path
        parts = tuple(_normalize_octets(part) for part in body.split("*"))
        # Count the normalized rule path, including its pattern operators,
        # rather than the variable number of URL characters consumed by '*'.
        specificity = sum(map(len, parts)) + len(parts) - 1 + int(anchored)
        return cls(parts, anchored, specificity, allow)

    def matches(self, path):
        if not path.startswith(self.parts[0]):
            return False
        if len(self.parts) == 1:
            return not self.anchored or path == self.parts[0]
        position = len(self.parts[0])
        # Ordered literal searches avoid regex backtracking on publisher data.
        for part in self.parts[1:-1]:
            found = path.find(part, position)
            if found < 0:
                return False
            position = found + len(part)
        last = self.parts[-1]
        if self.anchored:
            return len(path) - len(last) >= position and path.endswith(last)
        return path.find(last, position) >= 0


class PublisherRobotsPolicy:
    def __init__(self, lines):
        self.groups = []
        agents, rules = [], []
        saw_rule = False
        for raw in lines:
            field, separator, value = raw.split("#", 1)[0].partition(":")
            if not separator:
                continue
            field, value = field.strip().casefold(), value.strip()
            if field == "user-agent":
                if saw_rule:
                    self.groups.append((tuple(agents), tuple(rules)))
                    agents, rules, saw_rule = [], [], False
                if value:
                    agents.append(value.casefold())
            elif field in ("allow", "disallow") and agents:
                saw_rule = True
                # Empty rules have no effect; malformed relative paths and
                # rules before any user-agent cannot grant or deny access.
                if value.startswith(("/", "*")):
                    rules.append(_Rule.from_path(value, field == "allow"))
        if agents:
            self.groups.append((tuple(agents), tuple(rules)))

    def can_fetch(self, user_agent, url):
        product = user_agent.split("/", 1)[0].casefold()
        best_agent = -1
        selected = []
        for agents, rules in self.groups:
            # Preserve product-token matching, choosing the longest named
            # identity before '*' and merging all equally specific groups.
            score = max((0 if agent == "*" else len(agent)
                         for agent in agents if agent == "*" or agent in product), default=-1)
            if score > best_agent:
                best_agent, selected = score, list(rules)
            elif score == best_agent and score >= 0:
                selected.extend(rules)
        parsed = urlsplit(url)
        path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        path = _normalize_octets(path)
        if path == "/robots.txt":
            return True
        # Order is irrelevant: the longest matching rule wins, with Allow
        # taking an equal-length tie. No matching rule means allowed.
        return max(((rule.specificity, rule.allow) for rule in selected if rule.matches(path)),
                   default=(-1, True))[1]
