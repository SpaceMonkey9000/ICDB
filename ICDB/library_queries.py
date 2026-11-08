"""Small row projections for continuous lists; pin JSON is fetched only on selection."""
from builder import search_pattern


def definition_rows(db, term='', group='All pinouts', package='All packages'):
    pattern = search_pattern(term)
    return [dict(r) for r in db.execute('''
        WITH summary AS (
            SELECT d.id,json_extract(d.project_json,'$.device') AS title,
                json_extract(d.project_json,'$.package') AS family,
                json_extract(d.project_json,'$.package') || '-' || json_extract(d.project_json,'$.count') || CASE WHEN json_type(d.project_json,'$.exposed_pad')='object' AND coalesce(json_extract(d.project_json,'$.exposed_pad.enabled'),1)!=0 THEN '-EP' ELSE '' END AS package,
                (SELECT count(*) FROM pl_matches m WHERE m.definition_id=d.id AND m.status='Accepted') AS uses
            FROM pl_definitions d)
        SELECT * FROM summary s WHERE (?='All packages' OR s.family=?)
          AND (?='All pinouts' OR (?='Accepted groups' AND uses>0) OR (?='Without accepted parts' AND uses=0))
          AND (s.title LIKE ? ESCAPE '\\' OR s.package LIKE ? ESCAPE '\\'
               OR EXISTS (SELECT 1 FROM pl_matches m JOIN components c ON c.id=m.component_id
                 WHERE m.definition_id=s.id AND m.status='Accepted' AND
                 (c.part_number LIKE ? ESCAPE '\\' OR c.manufacturer LIKE ? ESCAPE '\\')))
        ORDER BY s.title COLLATE NOCASE,s.id
        ''',(package,package,group,group,group,pattern,pattern,pattern,pattern))]


def match_rows(db, term='', state='Suggested', rule='All rules', package='All packages',
               manufacturer='All manufacturers', view='All matches', scope='Component'):
    pattern = search_pattern(term)
    return [dict(r) for r in db.execute('''
        SELECT m.id,m.component_id,m.definition_id,m.status,m.rule,m.reason,m.blocked,
            c.part_number,c.manufacturer,c.function,
            json_extract(d.project_json,'$.device') AS title,
            json_extract(d.project_json,'$.package') || '-' || json_extract(d.project_json,'$.count') || CASE WHEN json_type(d.project_json,'$.exposed_pad')='object' AND coalesce(json_extract(d.project_json,'$.exposed_pad.enabled'),1)!=0 THEN '-EP' ELSE '' END AS package
        FROM pl_matches m JOIN components c ON c.id=m.component_id JOIN pl_definitions d ON d.id=m.definition_id
        WHERE (?='All' OR m.status=?) AND (?='All rules' OR m.rule=?)
          AND (?='All packages' OR json_extract(d.project_json,'$.package')=?)
          AND (?='All manufacturers' OR c.manufacturer=?)
          AND ((? IN ('Component','All fields') AND c.part_number LIKE ? ESCAPE '\\')
               OR (? IN ('Function','All fields') AND c.function LIKE ? ESCAPE '\\')
               OR (? IN ('Manufacturer','All fields') AND c.manufacturer LIKE ? ESCAPE '\\')
               OR (? IN ('Pinout','All fields') AND json_extract(d.project_json,'$.device') LIKE ? ESCAPE '\\'))
          AND (?='All matches'
               OR (?='Ready to accept' AND m.status='Suggested' AND m.blocked='' AND m.reason NOT LIKE '%CAUTION:%')
               OR (?='With cautions' AND m.reason LIKE '%CAUTION:%')
               OR (?='With conflicts' AND m.blocked!='')
               OR (?='Without accepted pinout' AND NOT EXISTS(SELECT 1 FROM pl_matches a WHERE a.component_id=m.component_id AND a.status='Accepted'))
               OR (?='With accepted pinout' AND EXISTS(SELECT 1 FROM pl_matches a WHERE a.component_id=m.component_id AND a.status='Accepted'))
               OR (?='Published' AND EXISTS(SELECT 1 FROM pl_publications p WHERE p.match_id=m.id AND p.link_id IS NOT NULL))
               OR (?='Not published' AND NOT EXISTS(SELECT 1 FROM pl_publications p WHERE p.match_id=m.id AND p.link_id IS NOT NULL)))
        ORDER BY d.id,c.part_number COLLATE NOCASE,m.id
        ''',(state,state,rule,rule,package,package,manufacturer,manufacturer,scope,pattern,scope,pattern,scope,pattern,scope,pattern,*([view]*8)))]


def group_members(db, ident):
    return [dict(r) for r in db.execute('''SELECT m.id,m.component_id,c.part_number,c.manufacturer,c.function
        FROM pl_matches m JOIN components c ON c.id=m.component_id
        WHERE m.definition_id=? AND m.status='Accepted' ORDER BY c.part_number COLLATE NOCASE''',(ident,))]


def available_components(db, ident, term=''):
    pattern = search_pattern(term)
    return [dict(r) for r in db.execute('''SELECT c.id,c.part_number,c.manufacturer,c.function FROM components c
        WHERE (c.part_number LIKE ? ESCAPE '\\' OR c.manufacturer LIKE ? ESCAPE '\\')
        AND NOT EXISTS (SELECT 1 FROM pl_matches m WHERE m.component_id=c.id AND m.definition_id=? AND m.status='Accepted')
        ORDER BY c.part_number COLLATE NOCASE''',(pattern,pattern,ident))]
