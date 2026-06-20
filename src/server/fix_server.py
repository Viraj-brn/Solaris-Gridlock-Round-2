with open("server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix 1: tags list
content = content.replace("tags = sorted([str(x) for x in raw_df['violation_type'].dropna().unique()])", "tags = sorted([c for c in raw_df.columns if c.startswith('viol_')])")

# Fix 2: tag filter
content = content.replace("filtered = filtered[filtered['violation_type'] == tag]", "filtered = filtered[filtered[tag] > 0]")

# Fix 3: lat/lng fallback for centroids
old_centroid_code = """                        if not c_row.empty:
                            lat = c_row['lat'].values[0]
                            lng = c_row['lng'].values[0]"""
new_centroid_code = """                        if not c_row.empty:
                            if 'lat_mean' in c_row:
                                lat = float(c_row['lat_mean'].values[0])
                                lng = float(c_row['lon_mean'].values[0])
                            else:
                                lat = float(c_row['lat'].values[0])
                                lng = float(c_row['lng'].values[0])"""
content = content.replace(old_centroid_code, new_centroid_code)

# Fix 4: top_tag mode
old_top_tag = "top_tag = zone_data['violation_type'].mode()[0] if not zone_data['violation_type'].mode().empty else \"Unknown\""
new_top_tag = "viol_cols = [c for c in zone_data.columns if c.startswith('viol_')]; top_tag = zone_data[viol_cols].sum().idxmax() if len(viol_cols) > 0 else 'Unknown'"
content = content.replace(old_top_tag, new_top_tag)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed server.py")
