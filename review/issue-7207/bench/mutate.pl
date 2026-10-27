#!/usr/bin/env perl
use strict;
use warnings;

# Intentional mutants for regression verification. The runner restores source.
my ($name, $path) = @ARGV;
die "Usage: mutate.pl NAME SOURCE\n" unless defined $path;
open my $input, '<', $path or die "$path: $!";
my $text = do { local $/; <$input> };
close $input;
my $changes = 0;
my $cleanup = qr/Box::pin\(\s*cleanup_index_dirs\(\s*object_store,\s*commit_handler,\s*&dataset\.base,\s*&index_ids,?\s*\)\s*\)\s*\.await;/;

if ($name eq 'terminal_cleanup') {
    $changes = ($text =~ s/$cleanup(\s*return Err\(err\);)/$1/);
} elsif ($name eq 'latest_guard') {
    $changes = ($text =~ s/for id in ids\.difference\(&live_ids\)/for id in ids/);
} elsif ($name eq 'keep_filter') {
    $changes = ($text =~ s/\n\s*\.filter\(\|index\| index\.new_id != index\.old_id\)//);
} elsif ($name eq 'initial_fri') {
    $changes = ($text =~ s/\n\s*ids\.extend\(frag_reuse_index\.iter\(\)\.map\(\|index\| index\.uuid\)\);//);
} elsif ($name eq 'rebased_fri') {
    $changes = ($text =~ s/\n\s*index_ids\.insert\(index\.uuid\);//);
} elsif ($name eq 'tagged_fri') {
    $changes = ($text =~ s/\n\s*index_ids\.insert\(assembly\.entry\.uuid\);//);
} elsif ($name eq 'prewrite_cleanup') {
    $changes = ($text =~ s/(\/\/ pre-write rejection also proves nonpublication by us\.\n)\s*$cleanup/$1/);
} elsif ($name eq 'exhaustion_cleanup') {
    $changes = ($text =~ s/$cleanup(\s*Err\(crate::Error::commit_conflict_source\()/$1/);
} elsif ($name eq 'borrowed_remaps') {
    $changes = ($text =~ s/matches!\(ownership, IndexOwnership::BuiltinCompaction\)/matches!(ownership, IndexOwnership::BuiltinCompaction | IndexOwnership::Compaction)/);
} elsif ($name eq 'cleanup_between_retries') {
    $changes = ($text =~ s/(if next_attempt_i < num_attempts \{\n)/$1 . "                    Box::pin(cleanup_index_dirs(object_store, commit_handler, \&dataset.base, \&index_ids)).await;\n"/e);
} elsif ($name eq 'delete_error_is_fatal') {
    $changes = ($text =~ s/Err\(error\) => log::warn!\(\s*"Failed to clean up uncommitted index directory '\{\}': \{\}",\s*path,\s*error\s*\),/Err(error) => panic!("cleanup delete failed: {error}"),/);
} elsif ($name eq 'read_error_deletes') {
    $changes = ($text =~ s/Err\(error\) => \{\s*log::warn!\(\s*"Skipping uncommitted index cleanup under '\{\}': cannot read the latest indices: \{\}",\s*base_path,\s*error\s*\);\s*return;\s*\}/Err(_error) => HashSet::new(),/);
} elsif ($name eq 'known_landed_cleanup') {
    # The last occurrence is commit_transaction's verified-own error arm.
    my $marker = 'if commit_handler.propagate_commit_error_after_success() {';
    my $position = rindex($text, $marker);
    die "Missing verified-own error gate\n" if $position < 0;
    substr($text, $position + length($marker), 0) =
        "\n                            Box::pin(cleanup_index_dirs(object_store, commit_handler, \&dataset.base, \&index_ids)).await;";
    $changes = 1;
} else {
    die "Unknown mutation: $name\n";
}
die "$name matched $changes locations, expected one\n" unless $changes == 1;
open my $output, '>', $path or die "$path: $!";
print {$output} $text;
close $output or die "$path: $!";
