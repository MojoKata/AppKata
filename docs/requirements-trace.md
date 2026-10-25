# Requirements and the tests that show them

Every sentence of a requirement either promises something observable or explains. A promise
nobody shows is a decision recorded but never built — the class behind most of review 2's
findings (the "Disable the app's own updater" option of 17.12, the "Show the launch command" of
17.4, the "if declined" prompt of 17.10). `tests/test_requirements_trace.py` splits each covered
section into sentences (and table rows) the way this table does and fails when a sentence has no
row, a row no longer matches its sentence, a named test doesn't exist, or the rows still open
differ from its list (review 3, harness B).

**Shown by** names, comma-separated:
- a test function (`test_…`, found in `tests/`), or a harness mode (`harness:<mode>`, in
  `scripts/test-sandbox.sh`);
- `claim` — a third-party fact, with its evidence in `docs/app-sandboxing.md`'s claims table;
- `open: <id>` — a finding that keeps it unshown (`R2-…` in `docs/reviews/app-sandboxing-2.md`,
  `R3-…` in `app-sandboxing-3.md`);
- `deferred` — listed in 17.18; `statement` — explains, names a file or a limit, promises nothing
  a test could show.

**Sentence starts** is the sentence's opening words with Markdown emphasis and backticks dropped.

## 17. App sandboxing (Linux)

| Req | Sentence starts | Shown by |
|---|---|---|
| 17.1 | Linux only, and only the two portable kinds | test_only_appimages_and_tarballs_on_linux_get_a_sandbox |
| 17.1 | AppImage (appimage) and tarball (tarball). | test_activate_generates_launcher_and_points_everything_at_it, test_appimage_launcher_extracts_lazily_and_sets_env |
| 17.1 | AppKata itself is never sandboxed, though run | test_appkata_itself_is_never_sandboxed_and_a_launcher_an_older_one_gave_it_goes, test_the_lifecycle_invariants_hold_over_random_walks_but_the_listed |
| 17.1 | Out of scope: .deb/.rpm | statement |
| 17.1 | The sandbox is built on bubblewrap | statement |
| 17.1 | A sandbox needs bwrap alone: where xdg-dbus-proxy is missing | test_bwrap_alone_sandboxes_and_a_standard_app_gets_no_bus_without_the_proxy, test_a_standard_app_without_xdg_dbus_proxy_runs_sandboxed_with_no_session_bus, test_the_support_status_matches_what_each_levels_launcher_does_but_the_listed, test_the_lifecycle_invariants_hold_over_random_walks_but_the_listed |
| 17.1 | App Detail and Settings → Sandbox name the missing tool | test_support_names_the_tool_that_is_missing, test_app_detail_says_a_standard_app_runs_without_desktop_services_where_the_proxy_is_missing, test_settings_sandbox_says_the_systems_support_and_reaches_its_setup |
| 17.1 | The launcher needs bwrap 0.5 or later | harness:launcher, harness:launcher-lmde7, harness:launcher-vm, harness:launcher-vm26, test_every_platform_1_1_supports_has_a_sandbox_tier_but_the_listed |
| 17.1 | On Ubuntu 22.04 the sandbox isn't tested | test_17_1_says_where_the_sandbox_is_not_tested |
| 17.1 | The containers run on the test machine's kernel | statement |
| 17.2 | Each app runs at one of three levels | test_templates_resolve_to_normalized_grant_sets |
| 17.2 | \| Off \| the real home | test_off_bypasses_the_sandbox, test_off_uses_the_program_directly_no_launcher |
| 17.2 | \| Standard \| private, plus granted folders | test_standard_launcher_has_proxy_and_private_home, test_standard_apps_reach_the_filtered_bus_when_there_is_one, test_a_self_updating_app_can_change_its_folder_only_with_the_writable_grant |
| 17.2 | \| Strict \| private only | test_strict_launcher_has_no_bus_no_network, test_strict_app_runs_and_cannot_read_the_real_home, test_no_network_grant_means_no_network, test_17_2s_strict_row_is_what_the_strict_launcher_gives_but_the_listed |
| 17.2.1 | Grants adjust a level: a folder (any path | test_the_launcher_the_chips_and_the_marker_agree_with_the_grant_set, test_the_dialog_can_make_every_change_that_runs_differently_but_the_listed, test_the_chips_tell_apart_every_change_that_runs_differently_and_no_other_but_the_listed |
| 17.2.1 | "Off" bypasses the launcher entirely | test_off_uses_the_program_directly_no_launcher |
| 17.2.1 | Grants adjust Standard: at Strict the table above | test_strict_drops_every_grant_that_would_widen_it |
| 17.2.1 | The Sandbox dialog switches the set to Standard | test_customizing_in_the_sandbox_dialog_round_trips_and_strict_widens |
| 17.2.1 | The X11 device grant is about the display | test_strict_drops_every_grant_that_would_widen_it, test_on_wayland_x11_apps_get_xwayland_only_with_the_grant, test_the_chips_tell_apart_every_change_that_runs_differently_and_no_other_but_the_listed |
| 17.2.1 | The Sandbox dialog adds the user's Documents, Downloads | test_the_user_folders_are_this_systems_own_names_and_only_those_that_exist, test_the_dialog_can_make_every_change_that_runs_differently_but_the_listed |
| 17.3 | A sandbox is normally picked as a named | test_templates_resolve_to_normalized_grant_sets, test_picking_a_template_in_the_sandbox_dialog_applies_that_template |
| 17.3 | \| strict \| Strict \| none | test_strict_drops_every_grant_that_would_widen_it |
| 17.3 | \| standard \| Standard | test_templates_resolve_to_normalized_grant_sets |
| 17.3 | \| offline-editor \| Standard | test_templates_resolve_to_normalized_grant_sets, test_a_folder_template_offers_its_folder_in_place_and_keeps_its_name, test_a_folder_template_says_no_folder_yet_until_it_has_one |
| 17.3 | \| online-app \| Standard | test_templates_resolve_to_normalized_grant_sets |
| 17.3 | \| messenger \| Standard | test_templates_resolve_to_normalized_grant_sets, test_the_tray_capability_starts_the_proxy_and_lets_the_app_own_its_item_name |
| 17.3 | \| media-player \| Standard | test_templates_resolve_to_normalized_grant_sets, test_a_folder_template_offers_its_folder_in_place_and_keeps_its_name, test_a_folder_template_says_no_folder_yet_until_it_has_one |
| 17.3 | \| developer \| Standard | test_templates_resolve_to_normalized_grant_sets, test_a_folder_template_offers_its_folder_in_place_and_keeps_its_name, test_a_folder_template_says_no_folder_yet_until_it_has_one |
| 17.3 | \| cli-tool \| Standard | test_cli_launcher_binds_the_current_directory, test_cli_tool_sees_and_writes_the_project_folder_it_is_run_in |
| 17.3 | The three made for a folder come with | test_a_folder_template_offers_its_folder_in_place_and_keeps_its_name, test_a_folder_template_says_no_folder_yet_until_it_has_one, test_the_install_cards_folder_link_opens_the_dialog_on_its_template_and_adopts_what_is_saved |
| 17.3.1 | Explicit settings override a template; | test_parse_folders_prefixes_and_modes, test_config_from_review_reads_sandbox_settings, test_one_review_can_say_every_change_that_runs_differently_but_the_listed, test_a_review_the_user_writes_carries_their_sandbox_but_the_listed, test_the_review_lines_round_trip_through_the_file, test_saving_a_review_writes_the_users_own_sandbox_whole_and_only_when_included |
| 17.3.1 | Sandbox folders: +~/Zettlr adds to the template's set | test_parse_folders_prefixes_and_modes |
| 17.3.1 | A template is resolved to a grant set | test_merge_across_trusts_is_least_privilege, test_whatever_the_resolver_reports_can_be_sent_back_to_it |
| 17.3.1 | Some folders are never shared, whoever asks | test_protected_folders_are_never_granted, test_a_grant_of_the_home_folder_or_the_keys_does_not_open_them, test_every_file_the_distributions_default_bashrc_sources_is_refused |
| 17.3.1 | Mint's Nemo has ~/.local/share/nemo/scripts | test_protected_folders_are_never_granted |
| 17.3.1 | Such a grant is dropped — the launcher | test_launcher_and_summary_refuse_protected_folders, test_a_custom_sandbox_cannot_share_a_protected_folder |
| 17.3.1 | The list is _protected_roots() in | statement |
| 17.3.1 | A folder is named from / or ~ | test_a_folder_not_named_from_the_root_or_home_is_refused_and_never_bound, test_a_review_naming_a_relative_folder_never_opens_the_real_home |
| 17.3.1 | Sandbox folders: home bound the real /home). | statement |
| 17.3.1 | Secrets are refused when a review asks | test_a_secret_folder_is_one_a_review_cannot_grant_but_the_user_can, test_the_users_own_secret_folder_stands_with_a_warning |
| 17.3.1 | A review's request shows as refused | test_a_review_cannot_grant_a_secret_folder_and_the_summary_says_so |
| 17.3.1 | The list is _secret_roots() in | statement |
| 17.3.1 | The keyring capabilities (saved passwords, the password | test_saving_a_review_writes_the_users_own_sandbox_whole_and_only_when_included, test_one_review_can_say_every_change_that_runs_differently_but_the_listed |
| 17.3.2 | Resolving several sources. | statement |
| 17.3.2 | When reviews and the user both weigh in | statement |
| 17.3.2 | Each review → a grant set | test_config_from_review_reads_sandbox_settings, test_a_review_line_round_trips_to_the_same_grant_set |
| 17.3.2 | Across Trusts → the least-privilege combination | test_merge_across_trusts_is_least_privilege, test_folder_only_if_all_trusts_grant_it, test_execute_deny_is_contagious, test_merging_never_widens_and_is_symmetric |
| 17.3.2 | One careless reviewer can't widen an app. | test_merging_never_widens_and_is_symmetric |
| 17.3.2 | The user's own choice wins over the merged | test_user_choice_wins_and_unreviewed_defaults, test_choose_precedence |
| 17.3.2 | A review's off adds no limit when merged | test_an_off_review_adds_no_limit_of_its_own, test_a_review_saying_off_is_only_a_suggestion_and_the_reviewed_baseline_applies, test_a_review_saying_off_needs_the_users_click, test_a_reviews_off_is_offered_on_the_install_card_and_applied_only_by_a_click |
| 17.3.3 | Defaults, by app kind and review state. | statement |
| 17.3.3 | Reviewed beats unreviewed. | test_default_template_by_kind_and_review_state |
| 17.3.3 | A reviewed GUI app uses the review's template | test_default_template_by_kind_and_review_state, test_user_default_applies_only_to_unreviewed_apps |
| 17.3.3 | Every default is one click to change in | test_picking_a_template_in_the_sandbox_dialog_applies_that_template, test_the_install_dialog_sends_a_sandbox_only_when_the_card_was_touched |
| 17.3.3 | The app's kind is decided from the download | test_a_tarballs_kind_comes_from_its_program_and_a_tool_gets_no_menu_entry, test_an_appimages_kind_is_read_by_its_runtime_inside_a_sandbox, test_a_program_is_an_app_when_it_links_a_display_library |
| 17.3.3 | What can't be told (a script, no bwrap) | test_a_tarball_says_so_in_its_desktop_file_else_its_program_decides, test_an_appimage_without_bwrap_is_unknown |
| 17.3.3 | The user's own choice in the install options | test_an_apps_kind_is_the_users_word_then_the_downloads_then_an_app, test_the_install_dialogs_kind_choice_moves_the_sandbox_card_and_is_saved, test_the_install_dialogs_sandbox_card_is_what_planfor_computes |
| 17.3.3 | A command-line tool gets no app-menu entry when | test_a_tarballs_kind_comes_from_its_program_and_a_tool_gets_no_menu_entry |
| 17.3.3 | The cli-tool template binds the directory the tool | test_cli_tool_sees_and_writes_the_project_folder_it_is_run_in, test_a_cli_tool_run_from_a_refused_folder_is_still_given_its_file_arguments |
| 17.3.3 | The directory is not shared when it is | test_cli_tool_never_gets_the_home_or_above_or_appkata_areas, test_cli_launcher_protects_the_persistence_dirs_and_the_runtime_folder |
| 17.3.4 | Personal templates (naming the user's own paths) | deferred, test_a_customization_saved_as_any_template_plus_changes_is_the_same_grant_set, test_a_folder_template_offers_its_folder_in_place_and_keeps_its_name, test_customizing_in_the_sandbox_dialog_round_trips_and_strict_widens |
| 17.3.4 | The Sandbox dialog describes such a set by | test_customizing_in_the_sandbox_dialog_round_trips_and_strict_widens |
| 17.3.5 | What a review may do. | statement |
| 17.3.5 | Reviews are suggestions from people the user trusts | statement |
| 17.3.5 | On its own a review may pick a | test_a_review_saying_off_needs_the_users_click, test_a_review_cannot_grant_a_secret_folder_and_the_summary_says_so |
| 17.3.5 | The never-shared folders (17.3.1) are refused whoever | test_a_custom_sandbox_cannot_share_a_protected_folder, test_launcher_and_summary_refuse_protected_folders |
| 17.4 | For every sandboxed app AppKata generates | test_activate_generates_launcher_and_points_everything_at_it, test_the_startup_pass_regenerates_a_launcher_an_older_appkata_wrote, test_the_startup_pass_restores_every_file_the_launcher_relies_on, test_a_sandbox_chosen_in_install_options_for_an_installed_app_applies_at_once |
| 17.4 | Its text can be shown in App Detail | test_app_detail_shows_the_launch_command_and_the_audit_records_its_hash, test_the_startup_pass_rewrites_and_audits_a_launcher_per_app |
| 17.4 | It binds /usr and /etc read-only; mounts a | test_the_launchers_words_give_exactly_what_the_inventory_lists, test_what_an_app_sees_inside_is_exactly_what_the_inventory_lists, test_the_launcher_matches_its_golden, test_strict_app_runs_and_cannot_read_the_real_home, test_launcher_binds_the_xdg_font_icon_and_theme_dirs_read_only, test_a_file_handed_over_by_the_document_portal_is_readable_and_only_by_that_app, test_launcher_uses_the_filter_instead_of_a_new_session, test_the_app_outlives_the_process_that_started_it, test_terminal_input_injection_stays_blocked, test_what_each_personas_session_carries_reaches_the_app_but_the_listed, test_the_launcher_passes_no_variable_its_shell_made_up |
| 17.4 | Strict adds no network, no folder grants and | test_strict_launcher_has_no_bus_no_network, test_a_strict_app_fails_fast_on_every_desktop_road_and_never_falls_back_inside, harness:launcher |
| 17.4 | A Strict app can open only files in its private | test_a_strict_app_says_on_a_terminal_why_it_cannot_see_its_arguments, test_a_strict_apps_xdg_open_fails_plainly_instead_of_starting_a_browser_inside, test_a_strict_app_fails_fast_on_every_desktop_road_and_never_falls_back_inside, test_the_road_the_shim_covers_still_starts_the_first_browser_inside |
| 17.4 | The host's desktop entries (/usr/share/applications | test_the_hosts_desktop_entries_are_hidden_from_the_sandbox |
| 17.4 | GLib opens a link or file with the | test_a_glib_program_opens_links_on_the_host_even_when_the_host_has_a_handler, claim |
| 17.4 | Every mount destination under $HOME lies inside the | test_a_link_the_app_leaves_at_a_mount_point_is_not_followed, test_launcher_guards_every_mount_destination_under_home |
| 17.4 | The launcher's exact text is the goldens in | test_the_launcher_matches_its_golden, test_17_points_at_the_goldens_and_the_field_test_runs_appkatas_own_code |
| 17.5 | Filtered session bus. | statement |
| 17.5 | When the level uses the bus, the launcher | test_standard_launcher_has_proxy_and_private_home, test_a_standard_launch_leaves_no_proxy_running, test_an_app_whose_name_starts_with_a_digit_still_gets_the_bus, harness:inputmethod |
| 17.5 | An unfiltered bus lets an app reach org.freedesktop.systemd1 | test_the_portals_answer_a_sandboxed_app_as_a_host_caller |
| 17.5 | The portals see the app as a host | test_the_portals_see_the_app_as_a_host_caller_through_a_narrowed_proxy, test_the_portals_answer_a_sandboxed_app_as_a_host_caller |
| 17.5 | GTK4 is held by the FileChooser denial itself | harness:filedialogs, harness:filedialogs-lmde7, claim |
| 17.5.1 | The fiddly desktop-services an app may use | test_proxy_args_map_capabilities, test_the_notification_and_inhibit_portals_come_with_their_capabilities, test_a_media_key_daemon_can_drive_an_app_with_the_mpris_capability_and_only_that_app, test_the_direct_screensaver_name_takes_an_inhibit_only_with_the_capability, test_a_password_service_app_serves_a_host_client_only_with_the_provide_capability, harness:consumers, test_the_dialog_can_make_every_change_that_runs_differently_but_the_listed |
| 17.5.1 | The full mapping table is in local-proxy-test-plan.md. | statement |
| 17.6 | The launcher presents each app a stable id | test_identity_is_a_valid_bus_name, test_identity_marker_cannot_be_swapped_for_a_host_file |
| 17.6 | PipeWire/WirePlumber take the app for a sandboxed client | harness:wayland, claim |
| 17.6 | The id is also the app's D-Bus name | test_an_app_whose_name_starts_with_a_digit_still_gets_the_bus, test_two_apps_with_one_name_get_their_own_folder_launcher_identity_and_home |
| 17.6 | A private home an uninstall keeps (17.14) stays | test_a_later_app_with_the_same_name_never_inherits_a_kept_private_home |
| 17.6 | AppKata records which app (URL) each home belongs | test_a_later_app_with_the_same_name_never_inherits_a_kept_private_home, test_a_home_removed_with_its_app_frees_the_name |
| 17.6 | A home with no owner recorded counts as | test_a_home_with_no_owner_recorded_counts_as_another_apps |
| 17.6.2 | A file or folder the app is given as an argument | test_a_file_argument_is_handed_over_to_a_standard_app, test_arguments_shaped_as_users_shape_them_reach_what_they_meant_but_the_listed |
| 17.6.2 | For a Standard app the launcher hands such | test_a_file_argument_is_handed_over_to_a_standard_app, test_launcher_hands_over_file_arguments_only_for_standard_apps |
| 17.6.2 | A path in a granted folder becomes the path | test_a_file_argument_is_handed_over_to_a_standard_app, test_a_cli_tool_run_from_a_refused_folder_is_still_given_its_file_arguments, test_arguments_shaped_as_users_shape_them_reach_what_they_meant_but_the_listed, test_file_arguments_in_a_granted_folder_become_the_path_the_app_sees, test_a_grant_reached_through_a_linked_home_maps_to_where_the_launcher_mounts_it, test_a_cli_tools_relative_paths_in_its_shared_folder_stay_as_typed |
| 17.6.2 | A file not yet made is not handed over | deferred |
| 17.6.2 | Strict apps have no bus and so no | test_launcher_hands_over_file_arguments_only_for_standard_apps |
| 17.6.2 | Without python3-gi or a running document portal the | test_file_arguments_pass_through_when_they_cannot_be_handed_over, test_a_document_portal_that_never_answers_only_delays_the_launch_and_passes_the_arguments_through |
| 17.6.1 | The portals see a host caller. xdg-desktop-portal 1.18 | claim |
| 17.6.1 | Decided: the bus proxy carries no marker, so | test_the_portals_answer_a_sandboxed_app_as_a_host_caller |
| 17.6.1 | AppKata never fabricates Flatpak instance records to pass | statement |
| 17.6.1 | The consequences: a file the user picks is | statement |
| 17.6.3 | File dialogs and opening things on the host. | statement |
| 17.6.3 | A sandboxed app's file dialog is its own | harness:filedialogs, test_the_portals_see_the_app_as_a_host_caller_through_a_narrowed_proxy |
| 17.6.3 | GTK4, Qt 6.5+ and Chromium/Electron read /.flatpak-info instead | harness:filedialogs, harness:filedialogs-lmde7, harness:consumers, claim |
| 17.6.3 | GTK4 is told not to ask: the launcher | harness:filedialogs-lmde7, claim |
| 17.6.3 | The flag is GTK's alone: | statement |
| 17.6.3 | GTK3 ignores it and never asked, and GLib's | harness:filedialogs, harness:consumers, claim |
| 17.6.3 | GTK4's other portal dialogs (print, colour) are the | statement |
| 17.6.3 | Qt 6.5+ reads the marker and probes the | harness:filedialogs-lmde7, claim |
| 17.6.3 | Qt up to 6.4 looks for the runtime-dir | harness:filedialogs, claim |
| 17.6.3 | Chromium/Electron reads version first, which is denied, and | harness:consumers, claim |
| 17.6.3 | Shown with real GTK3, GTK4 and Qt apps | harness:filedialogs, harness:filedialogs-lmde7, harness:consumers |
| 17.6.3 | The app's dialog then shows exactly what the | harness:filedialogs, test_standard_launcher_binds_the_apps_document_portal_view |
| 17.6.3 | An app whose own start script sets GTK_USE_PORTAL=1 | statement |
| 17.6.3 | AppKata does not undo that. | statement |
| 17.6.3 | Links and files the app wants opened on | test_links_and_files_an_app_opens_go_to_the_host_through_the_portal, test_a_sandboxed_app_gets_an_xdg_open_that_asks_the_host, harness:consumers |
| 17.6.3 | GLib and GTK apps call it on their | test_a_glib_program_opens_links_on_the_host_even_when_the_host_has_a_handler, harness:consumers |
| 17.6.3 | GLib prefers any handler it can find), Qt | harness:consumers, harness:filedialogs-lmde7, claim |
| 17.6.3 | The portal asks which program only when it | harness:consumers, claim |
| 17.6.3 | AppKata's xdg-open waits for the portal's answer and | harness:consumers |
| 17.6.3 | It is on the app's PATH at every | test_a_strict_apps_xdg_open_fails_plainly_instead_of_starting_a_browser_inside |
| 17.6.3 | That resolves a file in a granted folder | harness:consumers |
| 17.6.3 | It uses gdbus or busctl for URLs and | test_a_strict_app_fails_fast_on_every_desktop_road_and_never_falls_back_inside |
| 17.7 | An AppImage can't FUSE-mount inside bwrap, so: at | test_appimage_launcher_extracts_lazily_and_sets_env, test_a_replaced_appimage_is_extracted_again, test_an_appimage_cannot_swap_its_extraction_for_a_host_folder, claim |
| 17.7 | The .AppImage file is canonical (checksum, rollback, "run | test_removing_a_kept_appimage_version_drops_its_whole_cache, test_extraction_is_keyed_on_the_folder_and_the_stamp_not_on_apprun |
| 17.7 | APPDIR/APPIMAGE/ARGV0 are set. | test_appimage_launcher_extracts_lazily_and_sets_env |
| 17.7 | Extraction costs 2.5–3.5× the AppImage, shown in the | test_the_install_dialogs_sandbox_card_is_what_planfor_computes |
| 17.7.1 | Apps that keep settings or data beside the | test_writable_app_folder_binds_appdir_read_write, test_a_self_updating_app_can_change_its_folder_only_with_the_writable_grant |
| 17.7.1 | An AppImage's own .AppImage stays read-only whatever the | test_a_self_updating_appimage_can_change_its_unpacked_copy_but_never_the_appimage_itself |
| 17.8 | Audio reaches the app through the session manager | harness:wayland, claim |
| 17.8 | The grant is split into play and record | test_play_only_sound_is_not_shown_as_blocking_the_microphone |
| 17.8 | PipeWire and WirePlumber let a sandboxed client record | harness:wayland, claim |
| 17.8 | The camera grant binds the V4L2 devices (/dev/video* | test_the_camera_grant_binds_the_video_devices, test_the_portals_answer_a_sandboxed_app_as_a_host_caller |
| 17.9 | Display and the session warning. | statement |
| 17.9 | The Wayland socket is bound on a Wayland | test_wayland_display_reaches_the_app, test_x11_display_reaches_the_app |
| 17.9 | On Wayland the X11 (XWayland) socket is bound | test_on_wayland_x11_apps_get_xwayland_only_with_the_grant |
| 17.9 | Such an app can see and inject into | statement |
| 17.9 | Customize turns it off | test_the_x11_abstract_socket_follows_the_network_grant_not_the_x11_one, claim, test_the_chips_tell_apart_every_change_that_runs_differently_and_no_other_but_the_listed |
| 17.9 | Flatpak has the same property. | statement |
| 17.9 | The same holds for every abstract-namespace socket on the host | test_what_an_app_sees_inside_is_exactly_what_the_inventory_lists, test_the_bus_warning_is_on_exactly_where_a_dbus_launch_bus_is_reachable |
| 17.9 | AppKata warns about such a session in Settings → Sandbox | test_settings_and_app_detail_warn_about_an_abstract_session_bus_for_apps_with_the_network, test_the_bus_warning_is_said_only_for_an_abstract_session_bus |
| 17.9 | A desktop's own login uses systemd's user bus | claim |
| 17.9 | On X11, and on any Wayland compositor other | test_the_display_leak_warning_clears_only_gnome_wayland, harness:wayland, test_the_warning_matches_the_display_the_app_gets_and_what_its_compositor_leaks_but_the_listed, test_every_copy_of_the_warning_says_what_the_product_does_but_the_listed |
| 17.9 | KDE/kwin is in between: it hides screen capture | harness:kwin, harness:kwin-lmde7, test_the_display_leak_warning_clears_only_gnome_wayland, test_the_warning_matches_the_display_the_app_gets_and_what_its_compositor_leaks_but_the_listed |
| 17.9 | The session is the display the launcher gives the app: | test_the_warning_matches_the_display_the_app_gets_and_what_its_compositor_leaks_but_the_listed, test_the_display_leak_warning_clears_only_gnome_wayland |
| 17.9 | Wayland when $WAYLAND_DISPLAY names a socket in the runtime folder | test_the_warning_matches_the_display_the_app_gets_and_what_its_compositor_leaks_but_the_listed, test_the_display_leak_warning_clears_only_gnome_wayland |
| 17.9 | XDG_SESSION_TYPE doesn't decide it, since a compositor | test_the_display_leak_warning_clears_only_gnome_wayland, claim |
| 17.9 | Only GNOME Wayland needs no warning: the rule | test_the_display_leak_warning_clears_only_gnome_wayland, test_app_detail_shows_the_session_and_bus_caveats_the_backend_has |
| 17.9 | A desktop's name can mislead, though | test_the_warning_matches_the_display_the_app_gets_and_what_its_compositor_leaks_but_the_listed, test_the_fake_compositors_offer_what_the_table_says_they_leak, harness:wayland, harness:kwin, harness:kwin-lmde7 |
| 17.9 | The globals only add to the warning; | test_the_warning_matches_the_display_the_app_gets_and_what_its_compositor_leaks_but_the_listed, harness:wayland, harness:kwin, harness:kwin-lmde7 |
| 17.9 | AppKata's reading of sway, mutter and kwin 5 and 6 | harness:wayland, harness:kwin, harness:kwin-lmde7 |
| 17.10 | AppArmor setup (where the kernel restricts unprivileged user | statement |
| 17.10 | There bwrap won't run until an AppArmor profile | harness:launcher-vm, claim |
| 17.10 | AppKata detects this (a one-off bwrap --unshare-user probe) | test_setup_counts_only_when_bwrap_then_works, test_apps_installed_before_sandbox_support_get_their_launcher_once_it_works, test_the_support_status_matches_what_each_levels_launcher_does_but_the_listed, test_the_first_install_that_needs_the_sandbox_asks_to_set_it_up |
| 17.10 | It persists across reboots. | claim |
| 17.10 | The first need is installing an app that | test_the_first_install_that_needs_the_sandbox_asks_to_set_it_up, test_the_setup_prompt_is_only_for_the_first_need, test_the_setup_prompt_says_what_it_does_and_its_answers_reach_the_backend |
| 17.10 | Set up now runs the setup, then installs | test_the_first_install_that_needs_the_sandbox_asks_to_set_it_up, test_the_setup_prompt_says_what_it_does_and_its_answers_reach_the_backend |
| 17.10 | Not now installs it to run Off and | test_the_first_install_that_needs_the_sandbox_asks_to_set_it_up, test_the_setup_prompt_says_what_it_does_and_its_answers_reach_the_backend |
| 17.10 | Settings → Sandbox's Set up… and App Detail's standing | test_the_first_install_that_needs_the_sandbox_asks_to_set_it_up, test_app_detail_offers_the_system_setup_or_repair_and_reaches_it, test_settings_sandbox_says_the_systems_support_and_reaches_its_setup |
| 17.10 | A system without the restriction needs no setup; | harness:launcher-lmde7, test_this_system_boots_what_testing_md_says |
| 17.10 | The profile names the bwrap actually installed (the | test_profile_names_the_bwrap_actually_installed, test_setup_counts_only_when_bwrap_then_works |
| 17.10 | The setup checks bwrap as the user who | test_a_setup_whose_check_fails_for_the_user_leaves_nothing_installed |
| 17.10 | Once an app has a launcher it keeps one | test_an_app_with_a_launcher_keeps_it_on_a_broken_host, test_a_launcher_says_plainly_when_bwrap_is_missing, test_app_detail_says_an_app_that_keeps_its_launcher_on_a_broken_host_cant_start, test_the_lifecycle_invariants_hold_over_random_walks_but_the_listed |
| 17.10 | A failed check is asked again a minute | test_a_failed_userns_probe_is_asked_again_a_minute_later_and_a_pass_stands |
| 17.10.1 | What the profile costs. | statement |
| 17.10.1 | It is flags=(unconfined) with userns on the bwrap | test_profile_names_the_bwrap_actually_installed |
| 17.10.1 | But bwrap is a general tool, so the | statement |
| 17.10.1 | Settings → Sandbox and the per-app setup banner | test_settings_sandbox_says_the_systems_support_and_reaches_its_setup, test_app_detail_offers_the_system_setup_or_repair_and_reaches_it |
| 17.10.1 | AppKata does not install the tighter design that | statement |
| 17.10.1 | Ubuntu 25.04 and later ship it themselves (17.10.2). | claim |
| 17.10.2 | Ubuntu 25.04 and later. | statement |
| 17.10.2 | These ship their own AppArmor profile for /usr/bin/bwrap | harness:launcher-vm26, test_the_inner_sandbox_probe_tells_the_truth_inside_a_generated_launcher, claim |
| 17.10.2 | There the sandbox runs with no setup (the | harness:launcher-vm26, test_the_systems_own_bwrap_profile_is_found_and_nothing_else |
| 17.10.2 | So: - the setup refuses where the system | test_the_setup_is_refused_beside_the_systems_own_profile, test_support_says_conflict_beside_the_systems_profile_and_no_inner_sandbox_under_it, test_the_repair_removes_appkatas_profile_heals_and_is_audited |
| 17.10.2 | The launcher starts a program that brings that | test_a_chromium_app_gets_no_sandbox_only_where_its_own_cannot_run, test_a_chromium_app_gets_no_sandbox_exactly_where_its_own_cannot_run, claim |
| 17.10.2 | App Detail says so for such an app | test_app_detail_says_a_chromium_app_runs_without_its_own_sandbox_where_it_must |
| 17.10.2 | Whether the inner sandbox can run is probed | test_an_upgrade_to_a_system_with_its_own_bwrap_profile_rewrites_launchers_at_start, test_the_inner_sandbox_probe_tells_the_truth_inside_a_generated_launcher |
| 17.10.2 | Restoring the inner sandbox there is deferred (17.18). | deferred |
| 17.11 | Where permissions come from. | statement |
| 17.11 | In order: the user's per-app choice (install options | test_choose_precedence, test_user_choice_wins_and_unreviewed_defaults |
| 17.11 | Reviews never change an app's grants on their | test_a_changed_review_never_changes_an_installed_apps_grants, test_resaving_install_options_keeps_the_pin_the_seen_marker_and_the_users_choice |
| 17.11 | The badge names what the suggestion adds and removes; | test_the_review_badge_says_what_a_suggestion_adds_and_removes_and_what_that_means, test_app_detail_raises_the_review_badge_and_keep_mine_puts_it_down |
| 17.11 | Access is never silently widened. | test_a_changed_review_never_changes_an_installed_apps_grants, test_merging_never_widens_and_is_symmetric |
| 17.11 | The badge stands until the user acts on | test_the_review_badge_clears_once_the_user_acts_on_the_suggestion, test_use_theirs_in_the_sandbox_dialog_adopts_the_suggestion, test_a_sandbox_chosen_in_the_install_dialog_counts_as_seen |
| 17.11 | A later, different suggestion raises it again; a | test_the_review_badge_clears_once_the_user_acts_on_the_suggestion |
| 17.12 | An app that updates itself (4.10) can't while | test_a_self_updating_appimage_can_change_its_unpacked_copy_but_never_the_appimage_itself |
| 17.12 | So while it runs sandboxed — whenever it | test_a_self_updating_app_is_updated_by_appkata_while_it_runs_sandboxed, test_a_self_updating_app_that_runs_sandboxed_moves_to_versions_when_appkata_updates_it |
| 17.12 | App Detail says "It would update itself, but | test_app_detail_says_appkata_updates_a_self_updating_app_while_it_runs_sandboxed |
| 17.12 | Its own updater simply fails (how gracefully is | statement |
| 17.12 | Switched to Off, it updates itself again. | test_a_self_updating_app_is_updated_by_appkata_while_it_runs_sandboxed |
| 17.12 | (Review 2, F3: an earlier draft named a | statement |
| 17.13 | Enabling a sandbox after install warns that the | test_sandboxing_an_app_that_runs_unsandboxed_warns_before_save, test_the_lifecycle_invariants_hold_over_random_walks_but_the_listed |
| 17.13 | No automatic config import in v1 (17.18). | deferred |
| 17.13 | The warning comes before the change: the Sandbox | test_sandboxing_an_app_that_runs_unsandboxed_warns_before_save |
| 17.13 | Every way to set up system support (the | test_every_setup_entry_point_names_the_apps_it_will_sandbox, test_apps_sandboxed_by_appkata_are_named_before_and_after, test_the_waiting_note_tells_fresh_homes_from_kept_ones |
| 17.13 | When AppKata itself sandboxes an installed app (at | test_apps_sandboxed_by_appkata_are_named_before_and_after, test_an_update_that_first_sandboxes_an_app_says_so, test_the_lifecycle_invariants_hold_over_random_walks_but_the_listed |
| 17.14 | Uninstalling a sandboxed app offers to remove its | test_uninstall_leaves_only_what_it_promises_to_keep, test_uninstall_keeps_the_private_home_until_the_app_is_really_gone, test_the_uninstall_dialog_offers_to_delete_the_sandbox_home_but_the_listed |
| 17.14 | A kept home remains that app's alone (17.6). | test_a_later_app_with_the_same_name_never_inherits_a_kept_private_home |
| 17.15 | Settings → Sandbox (11.1): the default template for | test_user_default_applies_only_to_unreviewed_apps, test_settings_sandbox_defaults_reach_the_backend, test_settings_sandbox_says_the_systems_support_and_reaches_its_setup |
| 17.15 | "Follow reviewers' suggestions"; the review-badge toggle (17.11); a | test_app_detail_raises_the_review_badge_and_keep_mine_puts_it_down, test_settings_sandbox_says_the_systems_support_and_reaches_its_setup |
| 17.15 | "Follow reviewers' suggestions" off takes the reviews out | test_follow_reviewers_off_uses_the_users_default_and_never_badges |
| 17.15 | The Sandbox dialog still says what the reviewers | test_follow_reviewers_off_uses_the_users_default_and_never_badges |
| 17.16 | The Audit (13) records every change of a | test_each_sandbox_mutation_writes_exactly_its_audit_entry, test_the_system_setup_is_audited_once_it_really_worked, test_the_repair_removes_appkatas_profile_heals_and_is_audited, test_the_audit_tells_apart_every_change_that_runs_differently_but_the_listed, test_the_lifecycle_invariants_hold_over_random_walks_but_the_listed |
| 17.17 | Limits, stated plainly in the UI and docs: | test_every_dialog_hint_has_a_row_in_the_evidence_table, test_the_bus_warning_is_said_only_for_an_abstract_session_bus |
| 17.17 | Flatpak has the same property); a kernel exploit | statement |
| 17.18 | Deferred to later releases (not v1): the Wayland | deferred |
| 17.18 | The real-hardware validation still owed is the checklist | test_the_field_test_checks_the_product_and_leaves_the_testers_home_alone |
