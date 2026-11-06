import type { OpportunityGroup } from '../../api/client'

/** How a directory group is described. A same-name bucket is never presented as one confirmed company. */
export function groupDescription(group: OpportunityGroup): { kind: string | null; text: string; identities: string | null } {
  if (group.group_kind === 'same_name_unconfirmed') {
    return { kind: 'Name group', text: 'Same source-reported name; company identities are not linked.', identities: group.identity_count !== undefined ? `${group.identity_count} separate company ${group.identity_count === 1 ? 'identity' : 'identities'}` : null }
  }
  const unresolved = group.group_kind === 'unresolved' || group.role === 'unresolved'
  const role = unresolved ? 'Operator/customer unresolved' : group.role === 'operator' ? 'Operator' : 'Customer'
  return { kind: null, text: `${role}${group.operator_number ? ` · Operator ${group.operator_number}` : ''}`, identities: null }
}
