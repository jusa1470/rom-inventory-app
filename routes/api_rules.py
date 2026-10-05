from flask import Blueprint, jsonify, request, session

import db.database as db
from services.feature_parser import apply_features

bp = Blueprint("rules", __name__)


def _require_auth():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    return None


@bp.get("/api/rules")
def list_rules():
    err = _require_auth()
    if err:
        return err
    return jsonify({"items": db.get_feature_rules(
        sort=request.args.get("sort", "priority_desc"),
        q_text=request.args.get("q", "").strip(),
        q_value=request.args.get("q_value", "").strip(),
        match_type=request.args.get("match_type", "").strip(),
        action_type=request.args.get("action_type", "").strip(),
    )})


@bp.post("/api/rules")
def create_rule():
    err = _require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    required = ("match_text", "match_type", "action_type")
    if not all(data.get(k) for k in required):
        return jsonify({"error": f"Required: {', '.join(required)}"}), 400
    rule_id = db.create_feature_rule(data)
    return jsonify({"ok": True, "id": rule_id})


@bp.put("/api/rules/<int:rule_id>")
def update_rule(rule_id: int):
    err = _require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    db.update_feature_rule(rule_id, data)
    return jsonify({"ok": True})


@bp.delete("/api/rules/<int:rule_id>")
def delete_rule(rule_id: int):
    err = _require_auth()
    if err:
        return err
    db.delete_feature_rule(rule_id)
    return jsonify({"ok": True})


@bp.get("/api/rules/unknown")
def list_unknown():
    err = _require_auth()
    if err:
        return err
    resolved = request.args.get("resolved", "0") == "1"
    return jsonify({"items": db.get_unknown_features(resolved=resolved)})


@bp.post("/api/rules/unknown/<int:feature_id>/resolve")
def resolve_unknown(feature_id: int):
    err = _require_auth()
    if err:
        return err
    db.resolve_unknown_feature(feature_id)
    return jsonify({"ok": True})


@bp.post("/api/rules/preview")
def preview_rules():
    """Preview how a list of features would be parsed by current rules."""
    err = _require_auth()
    if err:
        return err
    data     = request.get_json(silent=True) or {}
    features = data.get("features") or []
    base_title = data.get("title") or ""
    result   = apply_features(features)
    from services.feature_parser import build_title
    return jsonify({
        "result":      result,
        "final_title": build_title(base_title, result),
    })
