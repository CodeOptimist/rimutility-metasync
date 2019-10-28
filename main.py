# Copyright (C) 2019  Christopher S. Galpin.  See /NOTICE.
import os, re, yaml, pathlib, sys
# from autohotkey import Script
from collections import defaultdict
from lxml import etree
from lxml.builder import E

global_yaml = {}
mod_yaml = {}


def main():
    global mod_yaml
    for yaml_path in sys.argv[1:]:
        if not os.path.isabs(yaml_path):
            yaml_path = os.path.join(os.getcwd(), yaml_path)
        if os.path.isdir(yaml_path):
            yaml_path = os.path.join(yaml_path, r'public.yaml')
        with open(yaml_path, encoding='utf-8') as f:
            _data = yaml.safe_load(f)

        mod_yaml = {}
        for k, v in _data.items():
            if k.startswith('global_'):
                global_yaml[k] = v
            else:
                mod_yaml[k] = v

        if 'features' not in mod_yaml:
            continue

        markup = get_steam_markup()
        about = get_about()
        updates = get_updates()
        settings = get_settings()

        dir_name = os.path.dirname(yaml_path)
        write_xml(dir_name, [prefer_local('about_path', ""), r'About\About.xml'], about)
        if updates.getchildren():
            write_xml(dir_name, [
                prefer_local('updates_path', ""),
                r'Defs\UpdateFeatures.xml',
                r'Defs\UpdateFeatureDefs\UpdateFeatures.xml',
            ], updates)
        if settings.getchildren():
            write_xml(dir_name, [prefer_local('settings_path', ""), r'Languages\English\Keyed\Settings.xml'], settings)

        # ahk = Script()
        # ahk.set('clipboard', markup)
        print('-' * 100)
        print(markup)
        print('-' * 100)


def prefer_local(key, default=None):
    if key is None:
        return default
    is_required = default is None
    if is_required:
        return mod_yaml.get(key, global_yaml['global_' + key])
    return mod_yaml.get(key, global_yaml.get('global_' + key, default))


def get_with_features(format_name, features=None, feature_filter=lambda x: x):
    if features is None:
        features = mod_yaml['features']

    default_feature_formats = {
        'steam': "[b]{feature_title}[/b]\n[i]{feature_steam}[/i]\n{feature_desc}",
        'about': "<color=white><b>{feature_title}</b></color>\n{feature_desc}",
        'update': "<color=white><b>{feature_title}</b></color>\n{feature_desc}",
    }
    feature_format = prefer_local(format_name + '_feature_format', default_feature_formats[format_name])

    lines = []
    for feature in filter(feature_filter, features):
        feature_lines = []
        feature_scope = defaultdict(str, {**{'feature_' + k: v for k, v in feature.items()}, **mod_yaml, **global_yaml})
        for line in feature_format.split("\n"):
            text = line.format_map(feature_scope).format_map(feature_scope)
            inner_text = re.sub(r'\[/?.*?]' if format_name == 'steam' else r'</?.*?>', '', text)
            if inner_text:
                feature_lines.append(text)
        lines.append("\n".join(feature_lines))
    features_text = "\n\n".join(lines)

    scope = defaultdict(str, {**mod_yaml, **global_yaml})
    scope['features'] = features_text  # for a friendly key name within formats
    format_ = prefer_local(format_name + '_format', "{features}")
    text = format_.format_map(scope).format_map(scope)
    if format_name != 'steam':
        text = markup_to_xml(text) + "\n"  # without ending \n, xml text can be cut off
    return text


def get_steam_markup():
    result = get_with_features('steam', feature_filter=lambda x: x.get('title'))
    return result


def get_about():
    description = get_with_features('about', feature_filter=lambda x: x.get('title'))
    supported_versions = E.supportedVersions()
    for v in prefer_local('supported_versions'):
        supported_versions.append(E.li(str(v)))
    result = E.ModMetaData(
        E.name(mod_yaml['name']),
        E.author(prefer_local('author')),
        E.url(prefer_local('url', "")),
        supported_versions,
        E.description(etree.CDATA(description)),
    )
    return result


def get_updates():
    result = E.Defs(
        E("HugsLib.UpdateFeatureDef",
          {'Abstract': "true", 'Name': "UpdateFeatureBase"},
          E.modNameReadable(mod_yaml['name']),
          E.modIdentifier(mod_yaml['identifier']),
          E.linkUrl(prefer_local('url', "")),
          )
    )

    def version_features():
        versions = set(x['at'] for x in mod_yaml['features'] if 'at' in x)
        _version_features = {v: [f for f in mod_yaml['features'] if f.get('at') == v] for v in versions}
        return _version_features

    reverse = prefer_local('descending_updates', True)
    for version, features in sorted(version_features().items(), reverse=reverse):
        update_scope = defaultdict(str, {'update_version': version.replace(r'.', r'_'), **mod_yaml, **global_yaml})
        content = get_with_features('update', features=features)
        element = E("HugsLib.UpdateFeatureDef",
                    {'ParentName': "UpdateFeatureBase"},
                    E.defName(
                        prefer_local('update_defname_format', "{identifier}_{update_version}").format_map(update_scope).format_map(update_scope)),
                    E.assemblyVersion(version),
                    E.content(etree.CDATA(content)),
                    )
        result.append(element)
    return result


def get_settings():
    def val(a, b):
        # so we can give a setting key an explicit blank value instead of inheriting the feature value
        return "" if a == "" else (a or b)

    gathered = defaultdict(lambda: defaultdict(str))
    for feature in mod_yaml['features']:
        for setting in feature.get('settings', []):
            name = setting['name']
            gathered[name]['title'] += (val(setting.get('title'), feature['title']))
            gathered[name]['desc'] += (val(setting.get('desc'), feature.get('desc', "")))

    result = E.LanguageData()
    for name, setting in gathered.items():
        setting_scope = defaultdict(str, {'setting_name': name, **mod_yaml, **global_yaml})
        title = E(prefer_local('setting_title_key_format', "{identifier}_{setting_name}_SettingTitle").format_map(setting_scope).format_map(setting_scope),
                  etree.CDATA(markup_to_xml(re.sub(r'\.$', r'', setting['title']))))
        result.append(title)
        desc = E(
            prefer_local('setting_desc_key_format', "{identifier}_{setting_name}_SettingDesc").format_map(setting_scope).format_map(setting_scope),
            etree.CDATA(markup_to_xml(setting['desc'])))
        result.append(desc)

    return result


def write_xml(base_path, rel_paths, root):
    paths = [os.path.join(base_path, rel_path) for rel_path in rel_paths if rel_path]
    exist_paths = (path for path in paths if os.path.exists(path))
    path = next(exist_paths, None) or paths[0]

    pathlib.Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, mode='wb') as f:
        f.write(etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=True))


def markup_to_xml(text):
    result = text
    url_format = prefer_local('xml_url_format', r'<color=grey><b>{text}</b></color>').format(url=r'\1', text=r'\2')
    result = re.sub(r'\[url=(.*?)](.*?)\[/url]', url_format, result, flags=re.DOTALL)
    u_format = prefer_local('xml_u_format', r'<color=grey>{text}</color>').format(text=r'\1')
    result = re.sub(r'\[u](.*?)\[/u]', u_format, result, flags=re.DOTALL)

    count = -1
    while count != 0:
        result, count = re.subn(r'\[(\w+)(=\w+)?](.*?)\[/\1]', r'<\1\2>\3</\1>', result, flags=re.DOTALL)
    return result


if __name__ == '__main__':
    main()
