@app.route("/api/list", methods=["POST"])
@require_user
def add_to_list():
    data = request.get_json(silent=True) or {}
    store_id = data.get("store_id")
    name = (data.get("name") or "").strip()
    if not name or not store_id:
        return jsonify({"error": "store_id and name required"}), 400
    db = get_db()

    # Verify store ownership
    store = db.execute(
        "SELECT id FROM stores WHERE id = ? AND household_id = ?",
        (store_id, _hh()),
    ).fetchone()
    if not store:
        db.close()
        return jsonify({"error": "store not found"}), 404

    existing = db.execute(
        "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?) AND purchased = 0",
        (store_id, _hh(), name),
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"ok": False, "duplicate": True, "existing_id": existing["id"]})

    # Ensure store item exists for auto-complete, and copy its category
    cat_row = db.execute(
        "SELECT id, category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?)",
        (store_id, _hh(), name),
    ).fetchone()
    existing_category = (cat_row["category"] if cat_row else "")
    if not existing_category:
        existing_category = categorize(name)

    if not cat_row:
        db.execute(
            "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
            (_hh(), store_id, name, existing_category),
        )
    elif existing_category and not cat_row["category"]:
        db.execute(
            "UPDATE store_items SET category = ? WHERE id = ?",
            (existing_category, cat_row["id"]),
        )

    db.execute(
        "INSERT INTO list_items (household_id, store_id, name, category, added_by) VALUES (?, ?, ?, ?, ?)",
        (_hh(), store_id, name, existing_category, get_display_name()),
    )
    db.commit()
    rowid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return jsonify({"ok": True, "id": rowid})
