"""Small row projections for continuous lists; pin JSON is fetched only on selection."""
from builder import search_pattern


def definition_rows(db, term='', group='All pinouts', package='All packages'):
    pattern = search_pattern(term)
    return [dict(r) for r in db.execute('''
        WITH summary AS (
            SELECT d.id,json_extract(d.project_json,'$.device') AS title,
                json_extract(d.project_json,'$.package') AS family,
                json_extract(d.project_json,'$.package') || '-' || json_extract(d.project_json,'$.count') || CASE WHEN json_type(d.project_json,'$.exposed_pad')='object' AND coalesce(json_extract(d.project_json,'$.exposed_pad.enabled'),1)!=0 THEN '-EP' ELSE '' END AS package,
                (SELECT count(*) FROM pl_assignments m WHERE m.definition_id=d.id) AS uses
            FROM pl_definitions d)
        SELECT * FROM summary s WHERE (?='All packages' OR s.family=?)
          AND (?='All pinouts' OR (?='Assigned groups' AND uses>0) OR (?='Without assigned parts' AND uses=0))
          AND (s.title LIKE ? ESCAPE '\\' OR s.package LIKE ? ESCAPE '\\'
               OR EXISTS (SELECT 1 FROM pl_assignments m JOIN components c ON c.id=m.component_id
                 WHERE m.definition_id=s.id AND
                 (c.part_number LIKE ? ESCAPE '\\' OR c.manufacturer LIKE ? ESCAPE '\\')))
        ORDER BY s.title COLLATE NOCASE,s.id
        ''',(package,package,group,group,group,pattern,pattern,pattern,pattern))]


def group_members(db, ident):
    return [dict(r) for r in db.execute('''SELECT m.id,m.component_id,c.part_number,c.manufacturer,c.function
        FROM pl_assignments m JOIN components c ON c.id=m.component_id
        WHERE m.definition_id=? ORDER BY c.part_number COLLATE NOCASE''',(ident,))]


def available_components(db, ident, term=''):
    pattern = search_pattern(term)
    return [dict(r) for r in db.execute('''SELECT c.id,c.part_number,c.manufacturer,c.function FROM components c
        WHERE (c.part_number LIKE ? ESCAPE '\\' OR c.manufacturer LIKE ? ESCAPE '\\')
        AND NOT EXISTS (SELECT 1 FROM pl_assignments m WHERE m.component_id=c.id AND m.definition_id=?)
        ORDER BY c.part_number COLLATE NOCASE''',(pattern,pattern,ident))]
